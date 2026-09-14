"""Read-only Codex GUI and rollout integration.

This module deliberately treats the Codex GUI's DevTools endpoint as an
optional, local observation point.  It never sends a command to Codex and it
never writes to the rollout directory.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


UUID_RE = re.compile(
    r"(?i)(?<![0-9a-f])([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-f])"
)


def _uuid_values(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [match.group(1).lower() for match in UUID_RE.finditer(value)]


def _normalise_uuid(value: str | None) -> str | None:
    values = _uuid_values(value or "")
    return values[0] if len(values) == 1 else None


@dataclass(frozen=True)
class ProbeCandidate:
    thread_id: str
    source: str
    score: int
    detail: str = ""


@dataclass(frozen=True)
class ThreadProbe:
    thread_id: str | None
    page_url: str | None = None
    candidates: tuple[ProbeCandidate, ...] = ()
    error: str | None = None


def choose_thread_id(candidates: Iterable[ProbeCandidate]) -> str | None:
    """Return a UUID only when the evidence has a clear winner.

    Location and active-router evidence outrank generic DOM links.  Ties are
    intentionally rejected: choosing a random historical link would be worse
    than hiding the panel until the GUI exposes an unambiguous current route.
    """

    ordered = sorted(candidates, key=lambda item: item.score, reverse=True)
    if not ordered:
        return None
    best_score = ordered[0].score
    best_ids = {item.thread_id for item in ordered if item.score == best_score}
    return next(iter(best_ids)) if len(best_ids) == 1 else None


class _WebSocket:
    """Small client for the local CDP WebSocket, avoiding a package install."""

    def __init__(self, url: str, timeout: float = 0.8) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise ValueError(f"unsupported CDP websocket scheme: {parsed.scheme}")
        host = parsed.hostname or ""
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("refusing a non-loopback CDP websocket")
        port = parsed.port or 80
        self._socket = socket.create_connection((host, port), timeout=timeout)
        self._socket.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._socket.sendall(request)
        response = self._read_until(b"\r\n\r\n")
        if not response.startswith(b"HTTP/1.1 101"):
            raise OSError("CDP websocket handshake failed")

    def _read_until(self, marker: bytes) -> bytes:
        data = bytearray()
        while marker not in data:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise OSError("CDP websocket closed during handshake")
            data.extend(chunk)
            if len(data) > 64 * 1024:
                raise OSError("CDP websocket handshake is too large")
        return bytes(data)

    def _send(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        length = len(masked)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        self._socket.sendall(header + mask + masked)

    def send_text(self, text: str) -> None:
        self._send(1, text.encode("utf-8"))

    def send_pong(self, payload: bytes) -> None:
        self._send(10, payload)

    def _read_exact(self, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = self._socket.recv(length - len(data))
            if not chunk:
                raise OSError("CDP websocket closed")
            data.extend(chunk)
        return bytes(data)

    def recv(self) -> tuple[int, bytes]:
        first, second = struct.unpack("!BB", self._read_exact(2))
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass


class CdpClient:
    """Discover the main Codex renderer and inspect its current route."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 0.8) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Codex CDP must stay on loopback")
        self.host = host
        self.port = port
        self.timeout = timeout
        self._message_id = 0

    def _json_list(self) -> list[dict[str, Any]]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.request("GET", "/json/list")
            response = connection.getresponse()
            if response.status != 200:
                raise OSError(f"CDP /json/list returned HTTP {response.status}")
            value = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        return value if isinstance(value, list) else []

    def _evaluate(self, websocket_url: str, expression: str) -> Any:
        websocket = _WebSocket(websocket_url, timeout=self.timeout)
        try:
            self._message_id += 1
            request_id = self._message_id
            websocket.send_text(
                json.dumps(
                    {
                        "id": request_id,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": expression,
                            "returnByValue": True,
                            "awaitPromise": True,
                        },
                    }
                )
            )
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                opcode, payload = websocket.recv()
                if opcode == 8:
                    raise OSError("CDP renderer closed")
                if opcode == 9:
                    websocket.send_pong(payload)
                    continue
                if opcode != 1:
                    continue
                message = json.loads(payload.decode("utf-8"))
                if message.get("id") != request_id:
                    continue
                result = message.get("result", {}).get("result", {})
                if result.get("subtype") == "error" or result.get("type") == "undefined":
                    return None
                return result.get("value")
            raise TimeoutError("CDP Runtime.evaluate timed out")
        finally:
            websocket.close()

    def probe(self) -> ThreadProbe:
        try:
            pages = self._json_list()
            page = next(
                (
                    item
                    for item in pages
                    if item.get("type") == "page"
                    and item.get("webSocketDebuggerUrl")
                    and str(item.get("url", "")).split("#", 1)[0] == "app://-/index.html"
                ),
                None,
            )
            if page is None:
                return ThreadProbe(None, error="Codex renderer page not found")
            snapshot = self._evaluate(str(page["webSocketDebuggerUrl"]), THREAD_PROBE_SCRIPT)
            if not isinstance(snapshot, dict):
                return ThreadProbe(None, page_url=page.get("url"), error="renderer probe returned no object")
            candidates = tuple(
                ProbeCandidate(
                    thread_id=str(item["thread_id"]).lower(),
                    source=str(item.get("source", "unknown")),
                    score=int(item.get("score", 0)),
                    detail=str(item.get("detail", "")),
                )
                for item in snapshot.get("candidates", [])
                if isinstance(item, dict) and _normalise_uuid(str(item.get("thread_id", "")))
            )
            return ThreadProbe(
                choose_thread_id(candidates),
                page_url=page.get("url"),
                candidates=candidates,
            )
        except Exception as exc:
            return ThreadProbe(None, error=f"{type(exc).__name__}: {exc}")


THREAD_PROBE_SCRIPT = r"""
(() => {
  const uuid = /(?<![0-9a-f])([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-f])/ig;
  const candidates = [];
  const add = (value, source, score, detail) => {
    if (typeof value !== 'string') return;
    uuid.lastIndex = 0;
    let match;
    while ((match = uuid.exec(value)) !== null) {
      candidates.push({thread_id: match[1].toLowerCase(), source, score, detail: detail || ''});
    }
  };
  add(location.href, 'location.href', 1000, location.href);
  add(location.hash, 'location.hash', 1000, location.hash);

  const historyValue = history.state;
  const walk = (value, path, depth) => {
    if (depth > 5 || value === null || value === undefined) return;
    if (typeof value === 'string') {
      const key = path.split('.').pop().toLowerCase();
      const routeKey = /(thread|conversation|chat|session|route|href|path)/.test(key);
      add(value, 'history.state', routeKey ? 940 : 620, path);
      return;
    }
    if (Array.isArray(value)) {
      value.slice(0, 40).forEach((item, index) => walk(item, `${path}[${index}]`, depth + 1));
      return;
    }
    if (typeof value === 'object') {
      Object.keys(value).slice(0, 80).forEach(key => walk(value[key], `${path}.${key}`, depth + 1));
    }
  };
  walk(historyValue, 'history.state', 0);

  const threadAttrs = ['data-thread-id', 'data-conversation-id', 'data-session-id', 'data-app-action-sidebar-thread-id'];
  const activeSelector = '[aria-current="page"], [aria-current="true"], [aria-selected="true"], [data-state="active"], [data-active="true"], [data-selected="true"], [data-app-action-sidebar-thread-active="true"], [data-app-action-sidebar-thread-selected="true"]';
  document.querySelectorAll(activeSelector).forEach((element) => {
    add(element.getAttribute('href'), 'active.href', 960, element.outerHTML.slice(0, 240));
    threadAttrs.forEach(name => add(element.getAttribute(name), `active.${name}`, 980, element.tagName));
    element.querySelectorAll('a[href], [data-thread-id], [data-conversation-id], [data-session-id], [data-app-action-sidebar-thread-id]').forEach(child => {
      add(child.getAttribute('href'), 'active.descendant.href', 970, child.textContent.trim().slice(0, 100));
      threadAttrs.forEach(name => add(child.getAttribute(name), `active.descendant.${name}`, 980, child.tagName));
    });
  });
  document.querySelectorAll('a[href], [data-thread-id], [data-conversation-id], [data-session-id], [data-app-action-sidebar-thread-id]').forEach((element) => {
    const visible = !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
    const score = visible ? 520 : 300;
    add(element.getAttribute('href'), 'dom.href', score, element.textContent.trim().slice(0, 100));
    threadAttrs.forEach(name => add(element.getAttribute(name), `dom.${name}`, score + 20, element.tagName));
  });
  return {href: location.href, candidates};
})()
"""


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, value: Any) -> "TokenUsage | None":
        if not isinstance(value, dict):
            return None
        try:
            return cls(
                input_tokens=int(value.get("input_tokens", 0) or 0),
                cached_input_tokens=int(value.get("cached_input_tokens", 0) or 0),
                output_tokens=int(value.get("output_tokens", 0) or 0),
                total_tokens=int(value.get("total_tokens", 0) or 0),
            )
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class UsageSnapshot:
    total: TokenUsage
    last: TokenUsage
    context_window: int | None
    primary_used_percent: float | None
    secondary_used_percent: float | None
    request_count: int


class UsageAccumulator:
    def __init__(self) -> None:
        self.total = TokenUsage()
        self.last = TokenUsage()
        self.context_window: int | None = None
        self.primary_used_percent: float | None = None
        self.secondary_used_percent: float | None = None
        self.request_count = 0

    def apply(self, record: dict[str, Any]) -> bool:
        if record.get("type") != "event_msg":
            return False
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            return False
        info = payload.get("info")
        if not isinstance(info, dict):
            return False
        total = TokenUsage.from_mapping(info.get("total_token_usage"))
        last = TokenUsage.from_mapping(info.get("last_token_usage"))
        if total is None or last is None:
            return False
        self.total = total
        self.last = last
        try:
            self.context_window = int(info["model_context_window"])
        except (KeyError, TypeError, ValueError):
            self.context_window = None
        limits = payload.get("rate_limits")
        if isinstance(limits, dict):
            for key, target in (("primary", "primary_used_percent"), ("secondary", "secondary_used_percent")):
                value = limits.get(key)
                if isinstance(value, dict) and value.get("used_percent") is not None:
                    try:
                        setattr(self, target, float(value["used_percent"]))
                    except (TypeError, ValueError):
                        pass
        self.request_count += 1
        return True

    def snapshot(self) -> UsageSnapshot | None:
        if not self.request_count:
            return None
        return UsageSnapshot(
            total=self.total,
            last=self.last,
            context_window=self.context_window,
            primary_used_percent=self.primary_used_percent,
            secondary_used_percent=self.secondary_used_percent,
            request_count=self.request_count,
        )


UUID_SUFFIX_RE = re.compile(r"-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", re.I)


def _record_aliases(record: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return aliases
    record_type = record.get("type")
    keys = ("id", "session_id") if record_type == "session_meta" else ("thread_id",)
    for key in keys:
        value = _normalise_uuid(str(payload.get(key, "")))
        if value:
            aliases.add(value)
    return aliases


@dataclass(frozen=True)
class RolloutInfo:
    path: Path
    aliases: tuple[str, ...]


class SessionIndex:
    """Map a GUI thread UUID to exactly one rollout file.

    The filename suffix is preferred because it is the stable identity used
    by the Codex session store.  Ambiguous metadata never falls back to the
    newest file.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("CODEX_SESSIONS_DIR", "~/.codex/sessions")).expanduser()
        self._by_alias: dict[str, list[Path]] = {}
        self._by_suffix: dict[str, list[Path]] = {}
        self._by_session_id: dict[str, list[Path]] = {}
        self.refresh()

    def refresh(self) -> None:
        by_alias: dict[str, list[Path]] = {}
        by_suffix: dict[str, list[Path]] = {}
        by_session_id: dict[str, list[Path]] = {}
        if not self.root.exists():
            self._by_alias, self._by_suffix = by_alias, by_suffix
            return
        for path in self.root.rglob("*.jsonl"):
            if not path.is_file():
                continue
            aliases: set[str] = set()
            session_ids: set[str] = set()
            match = UUID_SUFFIX_RE.search(path.name)
            if match:
                aliases.add(match.group(1).lower())
                by_suffix.setdefault(match.group(1).lower(), []).append(path)
            try:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    for index, line in enumerate(stream):
                        if index >= 128:
                            break
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(record, dict):
                            record_aliases = _record_aliases(record)
                            aliases.update(record_aliases)
                            if record.get("type") == "session_meta":
                                session_ids.update(record_aliases)
            except OSError:
                continue
            for alias in aliases:
                by_alias.setdefault(alias, []).append(path)
            for session_id in session_ids:
                by_session_id.setdefault(session_id, []).append(path)
        self._by_alias, self._by_suffix, self._by_session_id = by_alias, by_suffix, by_session_id

    @staticmethod
    def _newest(paths: list[Path]) -> Path | None:
        unique = list(dict.fromkeys(paths))
        if not unique:
            return None
        try:
            return max(unique, key=lambda path: (path.stat().st_mtime_ns, str(path)))
        except OSError:
            return None

    def resolve(self, thread_id: str | None) -> Path | None:
        normalized = _normalise_uuid(thread_id)
        if not normalized:
            return None
        suffixes = self._by_suffix.get(normalized, [])
        session_rollouts = self._by_session_id.get(normalized, [])
        if session_rollouts:
            # A GUI thread can have several rollout files (one per turn). The
            # newest file with the exact session_meta id is the live turn.
            return self._newest(session_rollouts)
        if len(suffixes) == 1:
            return suffixes[0]
        aliases = list(dict.fromkeys(self._by_alias.get(normalized, [])))
        return aliases[0] if len(aliases) == 1 else None

    def describe(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "rollouts": sum(len(paths) for paths in self._by_suffix.values()),
            "thread_ids": sorted(self._by_alias),
        }


class IncrementalRolloutReader:
    """Replay one rollout once, then consume only appended complete lines."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self._offset = 0
        self._tail = b""
        self._inode: int | None = None
        self._usage = UsageAccumulator()

    def clear(self) -> None:
        self.path = None
        self._offset = 0
        self._tail = b""
        self._inode = None
        self._usage = UsageAccumulator()

    def switch(self, path: str | Path | None) -> UsageSnapshot | None:
        target = Path(path) if path else None
        if target != self.path:
            self.clear()
            self.path = target
        return self.poll()

    def poll(self) -> UsageSnapshot | None:
        if self.path is None:
            return None
        try:
            stat = self.path.stat()
        except OSError:
            return None
        if self._inode is not None and (stat.st_ino != self._inode or stat.st_size < self._offset):
            self._offset = 0
            self._tail = b""
            self._usage = UsageAccumulator()
        self._inode = stat.st_ino
        try:
            with self.path.open("rb") as stream:
                stream.seek(self._offset)
                chunk = stream.read()
        except OSError:
            return self._usage.snapshot()
        data = self._tail + chunk
        parts = data.split(b"\n")
        if data.endswith(b"\n"):
            self._tail = b""
        else:
            self._tail = parts.pop() if parts else data
        # ``_offset`` points to the next unread byte in the file.  The tail
        # has already been read, so the next poll must seek after ``chunk``
        # and prepend the tail exactly once.
        self._offset += len(chunk)
        for raw in parts:
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                self._usage.apply(record)
        return self._usage.snapshot()


def rollout_summary(path: str | Path) -> dict[str, Any]:
    """Read a rollout once for the command-line diagnostic path."""

    reader = IncrementalRolloutReader()
    snapshot = reader.switch(path)
    return {"path": str(path), "snapshot": snapshot}
