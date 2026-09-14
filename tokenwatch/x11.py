"""Minimal X11 window attachment helpers for the companion GTK window."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


WINDOW_ID_RE = re.compile(r"0x[0-9a-f]+", re.I)


@dataclass(frozen=True)
class WindowInfo:
    xid: int
    x: int
    y: int
    width: int
    height: int
    minimized: bool
    maximized: bool


def _run(*args: str, timeout: float = 0.45) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    return result.stdout


def _properties(xid: int) -> str:
    return _run("xprop", "-id", hex(xid), "WM_CLASS", "_NET_WM_PID", "_NET_WM_NAME", "_NET_WM_STATE", "_NET_WM_WINDOW_TYPE")


def _geometry(xid: int) -> tuple[int, int, int, int] | None:
    try:
        text = _run("xwininfo", "-id", hex(xid), timeout=0.6)
    except (OSError, subprocess.SubprocessError):
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        for key in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
            if line.strip().startswith(key + ":"):
                try:
                    values[key] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
    if len(values) != 4:
        return None
    return values["Absolute upper-left X"], values["Absolute upper-left Y"], values["Width"], values["Height"]


def _client_ids() -> list[int]:
    try:
        root = _run("xprop", "-root", "_NET_CLIENT_LIST", "_NET_CLIENT_LIST_STACKING")
    except (OSError, subprocess.SubprocessError):
        return []
    return list(dict.fromkeys(int(value, 16) for value in WINDOW_ID_RE.findall(root)))


def active_window_xid() -> int | None:
    """Return the currently active top-level X11 window, if available."""

    try:
        root = _run("xprop", "-root", "_NET_ACTIVE_WINDOW")
    except (OSError, subprocess.SubprocessError):
        return None
    match = WINDOW_ID_RE.search(root)
    if not match or match.group(0).lower() == "0x0":
        return None
    return int(match.group(0), 16)


def _looks_like_codex(properties: str) -> bool:
    lower = properties.lower()
    if "tokenwatch" in lower:
        return False
    if any(marker in lower for marker in ("chatgpt", "codex")):
        return True
    pid_match = re.search(r"_net_wm_pid[^=]*=\s*(\d+)", lower)
    if pid_match:
        try:
            with open(f"/proc/{pid_match.group(1)}/cmdline", "rb") as stream:
                command = stream.read().replace(b"\0", b" ").decode("utf-8", "ignore")
        except OSError:
            command = ""
        return any(marker in command.lower() for marker in ("chatgpt", "codex"))
    return False


def find_codex_window() -> WindowInfo | None:
    """Find a visible X11 Codex window without depending on wmctrl/xdotool."""

    for xid in _client_ids():
        try:
            properties = _properties(xid)
        except (OSError, subprocess.SubprocessError):
            continue
        if not _looks_like_codex(properties):
            continue
        geometry = _geometry(xid)
        if geometry is None:
            continue
        state = properties.lower()
        return WindowInfo(
            xid=xid,
            x=geometry[0],
            y=geometry[1],
            width=geometry[2],
            height=geometry[3],
            minimized="_net_wm_state_hidden" in state,
            maximized=("_net_wm_state_maximized_horz" in state and "_net_wm_state_maximized_vert" in state),
        )
    return None


def set_transient_for(window_xid: int, parent_xid: int) -> None:
    """Set the relationship using X11 so the two independent windows travel together."""

    try:
        subprocess.run(
            [
                "xprop",
                "-id",
                hex(window_xid),
                "-f",
                "WM_TRANSIENT_FOR",
                "32c",
                "-set",
                "WM_TRANSIENT_FOR",
                hex(parent_xid),
            ],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
