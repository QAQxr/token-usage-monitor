"""GTK3 TokenWatch companion window."""

from __future__ import annotations

import argparse
import dataclasses
import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Any

from .codex import CdpClient, IncrementalRolloutReader, SessionIndex, ThreadProbe
from .render import render, render_markup, validate_layout
from .x11 import find_codex_window


def _snapshot_json(snapshot: Any) -> Any:
    return dataclasses.asdict(snapshot) if snapshot is not None else None


def probe_payload(root: str | Path) -> dict[str, Any]:
    index = SessionIndex(root)
    probe = CdpClient(timeout=0.35).probe()
    path = index.resolve(probe.thread_id)
    reader = IncrementalRolloutReader()
    snapshot = reader.switch(path)
    return {
        "cdp": {
            "thread_id": probe.thread_id,
            "page_url": probe.page_url,
            "error": probe.error,
            "candidates": [dataclasses.asdict(candidate) for candidate in probe.candidates],
        },
        "mapping": {"path": str(path) if path else None, "index": index.describe()},
        "snapshot": _snapshot_json(snapshot),
    }


def render_for_thread(root: str | Path, thread_id: str) -> str | None:
    index = SessionIndex(root)
    path = index.resolve(thread_id)
    if path is None:
        return None
    reader = IncrementalRolloutReader()
    snapshot = reader.switch(path)
    return render(snapshot) if snapshot else None


class GtkUnavailableError(RuntimeError):
    pass


def _acquire_instance_lock() -> Any | None:
    """Allow only one companion process, regardless of how it was launched."""
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")).expanduser()
    lock_file: Any | None = None
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (runtime_dir / "tokenwatch-companion.lock").open("w", encoding="utf-8")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except (OSError, ValueError):
        if lock_file is not None:
            try:
                lock_file.close()
            except OSError:
                pass
        return None


class CompanionApp:
    def __init__(self, root: str | Path, interval: float = 0.7) -> None:
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk, GLib, Gtk, Pango
        except Exception as exc:  # pragma: no cover - depends on host GUI packages
            raise GtkUnavailableError(f"GTK3/PyGObject is unavailable: {exc}") from exc

        init_result = Gtk.init_check([])
        initialized = init_result[0] if isinstance(init_result, tuple) else bool(init_result)
        if not initialized:  # pragma: no cover - depends on the active display
            raise GtkUnavailableError("GTK display could not be initialized")

        self.Gdk = Gdk
        self.GLib = GLib
        self.Gtk = Gtk
        self.Pango = Pango
        self.root = Path(root).expanduser()
        self.interval_ms = max(300, int(interval * 1000))
        self.index = SessionIndex(self.root)
        self.cdp = CdpClient(timeout=0.35)
        self.reader = IncrementalRolloutReader()
        self.thread_id: str | None = None
        self.rollout: Path | None = None
        self.window_xid: int | None = None
        self._global_above_applied = False
        self._placement_initialized = False
        self._last_programmatic_position: tuple[int, int] | None = None
        self.tick_count = 0
        self._status = ""

        self.window = Gtk.Window(title="TokenWatch")
        self.window.set_resizable(False)
        self.window.set_decorated(True)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.window.set_border_width(4)
        self.window.connect("destroy", Gtk.main_quit)
        self.window.connect("configure-event", self._on_configure)
        self.label = Gtk.Label()
        self.label.set_xalign(0.0)
        self.label.set_yalign(0.0)
        self.label.set_selectable(False)
        self.label.set_line_wrap(False)
        self.label.modify_font(Pango.FontDescription("Monospace 10"))
        self.window.add(self.label)
        self.window.hide()

    def _set_status(self, message: str) -> None:
        if message != self._status:
            self._status = message
            print(message, file=sys.stderr, flush=True)

    def _on_configure(self, _window: Any, _event: Any) -> bool:
        if not self._placement_initialized:
            return False
        position = self.window.get_position()
        if self._last_programmatic_position == position:
            self._last_programmatic_position = None
            return False
        return False

    def _show_attached(self, parent: Any | None = None) -> bool:
        parent = parent or find_codex_window()
        if parent is None or parent.minimized:
            self.window.hide()
            return False
        # Mapping an already-visible window on every timer tick can cause
        # some WMs to restack it above the active application.  Only map it
        # when transitioning from hidden to visible.
        if not self.window.get_visible():
            self.window.show_all()
        child = self.window.get_window()
        if child is None:
            return False
        get_xid = getattr(child, "get_xid", None)
        if get_xid is None:
            self.window.hide()
            self._set_status("TokenWatch: GTK is not using X11; set GDK_BACKEND=x11")
            return False
        self.window_xid = get_xid()
        # Default behavior: stay above all applications.  Apply the hint only
        # once after mapping so refreshes do not repeatedly restack the window.
        if not self._global_above_applied:
            self.window.set_keep_above(True)
            self._global_above_applied = True
        if not self._placement_initialized:
            width, height = self.window.get_size()
            if parent.maximized:
                default_x = parent.x + parent.width - width - 10
                default_y = parent.y + 10
            else:
                default_x = parent.x + parent.width + 8
                default_y = parent.y + 8
            screen = self.Gdk.Screen.get_default()
            x, y = default_x, default_y
            if screen is not None:
                monitor = screen.get_monitor_at_point(parent.x, parent.y)
                geometry = screen.get_monitor_geometry(monitor)
                x = max(geometry.x, min(x, geometry.x + geometry.width - width))
                y = max(geometry.y, min(y, geometry.y + geometry.height - height))
            target = (x, y)
            if self.window.get_position() != target:
                self._last_programmatic_position = target
                self.window.move(*target)
            self._placement_initialized = True
        return True

    def _hide(self) -> None:
        self.window.hide()

    def tick(self) -> bool:
        self.tick_count += 1
        if self.tick_count % 8 == 1:
            self.index.refresh()
        probe: ThreadProbe = self.cdp.probe()
        resolved_rollout = self.index.resolve(probe.thread_id) if probe.thread_id else None
        if probe.thread_id != self.thread_id or resolved_rollout != self.rollout:
            self.thread_id = probe.thread_id
            self.rollout = resolved_rollout
            self.reader.switch(self.rollout)
        snapshot = self.reader.poll() if self.rollout else None
        if probe.thread_id is None:
            self._set_status("TokenWatch: waiting for Codex CDP at 127.0.0.1:9222")
            self._hide()
            return True
        if self.rollout is None:
            self._set_status(f"TokenWatch: thread {probe.thread_id[:8]} has no unique rollout")
            self._hide()
            return True
        if snapshot is None:
            self._set_status("TokenWatch: selected rollout has no token usage yet")
            self._hide()
            return True
        lines = render(snapshot)
        validate_layout(lines.splitlines())
        # Keep the visible layout pure text while using Pango only to emphasize
        # dynamic numbers.  Markup tags do not affect the monospace columns.
        self.label.set_markup(render_markup(snapshot))
        parent = find_codex_window()
        if parent is None:
            self._set_status("TokenWatch: waiting for Codex X11 window")
            self._hide()
            return True
        if parent.minimized:
            self._set_status("TokenWatch: Codex is minimized")
            self._hide()
            return True
        self._set_status(f"TokenWatch: connected to {probe.thread_id[:8]}")
        self._show_attached(parent)
        return True

    def run(self) -> int:
        self.GLib.timeout_add(self.interval_ms, self.tick)
        self.tick()
        self.Gtk.main()
        return 0


def run_gtk(root: str | Path, interval: float = 0.7) -> int:
    # The attachment protocol is X11-specific.  On Ubuntu Wayland sessions,
    # GTK can still use the XWayland display exposed through DISPLAY.
    os.environ["GDK_BACKEND"] = os.environ.get("TOKENWATCH_GDK_BACKEND", "x11")
    lock_file = _acquire_instance_lock()
    if lock_file is None:
        print("TokenWatch: companion is already running", file=sys.stderr, flush=True)
        return 0
    try:
        return CompanionApp(root, interval).run()
    finally:
        lock_file.close()


def add_companion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--companion", action="store_true", help="run the pure-text GTK TokenWatch companion")
    parser.add_argument("--probe", action="store_true", help="print the loopback CDP probe and exact rollout mapping")
    parser.add_argument("--render-thread", metavar="UUID", help="render one mapped thread without opening a window")
    parser.add_argument("--render-file", type=Path, help="render one rollout file without opening a window")


def command_companion(args: argparse.Namespace, root: Path) -> int | None:
    if args.probe:
        print(json.dumps(probe_payload(root), ensure_ascii=False, indent=2))
        return 0
    if args.render_thread:
        value = render_for_thread(root, args.render_thread)
        if value is None:
            return 2
        print(value)
        return 0
    if args.render_file:
        reader = IncrementalRolloutReader()
        snapshot = reader.switch(args.render_file)
        if snapshot is None:
            return 2
        print(render(snapshot))
        return 0
    if args.companion or args.gui:
        try:
            return run_gtk(root, args.interval)
        except GtkUnavailableError as exc:
            print(str(exc))
            return 2
    return None
