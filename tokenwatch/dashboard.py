"""Dependency-free local HTTP dashboard."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .pipeline import DEFAULT_SESSION_ROOT, load_newest_store


class DashboardHandler(BaseHTTPRequestHandler):
    ui_root = Path(__file__).resolve().parent.parent / "ui"
    session_root = DEFAULT_SESSION_ROOT

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - standard library handler API
        path = urlparse(self.path).path
        if path == "/api/snapshot":
            rollout, store = load_newest_store(self.session_root)
            body = json.dumps(
                {
                    "source_file": str(rollout) if rollout else None,
                    "snapshot": store.snapshot(),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return

        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        candidate = (self.ui_root / relative).resolve()
        if self.ui_root not in candidate.parents and candidate != self.ui_root:
            self._send(403, "text/plain; charset=utf-8", b"forbidden")
            return
        if not candidate.is_file():
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        content_type = "text/html; charset=utf-8"
        if candidate.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif candidate.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        self._send(200, content_type, candidate.read_bytes())

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8765, session_root: str | Path = DEFAULT_SESSION_ROOT) -> None:
    DashboardHandler.session_root = Path(session_root)
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Token Usage Monitor: http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
