"""Qt-independent GUI helpers and the optional PySide6 entry point."""

from __future__ import annotations

import importlib.util
from typing import Any, Literal

from .monitor import latest_scope


class GuiUnavailableError(RuntimeError):
    """Raised when the optional PySide6 dependency is not installed."""


def format_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def format_percent(value: Any) -> str:
    return "—" if value is None else f"{float(value):.1f}%"


def format_duration(value: Any) -> str:
    if value is None:
        return "—"
    milliseconds = float(value)
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.2f}s"
    return f"{milliseconds:.0f}ms"


def format_rate(value: Any) -> str:
    return "—" if value is None else f"{float(value):,.1f} tok/s"


def format_context(scope: dict[str, Any] | None) -> str:
    if not scope or scope.get("context_window") is None:
        return "—"
    total = scope.get("total_tokens")
    window = scope["context_window"]
    if total is None:
        return format_number(window)
    return f"{format_number(total)} / {format_number(window)}"


def scope_values(snapshot: dict[str, Any], scope: Literal["session", "turn"]) -> dict[str, str]:
    current = latest_scope(snapshot, scope)
    if current is None:
        return {key: "—" for key in ("total", "input", "cached", "output", "cache", "ttft", "tps", "latency", "context")}
    return {
        "total": format_number(current.get("total_tokens")),
        "input": format_number(current.get("input_tokens")),
        "cached": format_number(current.get("cached_tokens")),
        "output": format_number(current.get("output_tokens")),
        "cache": format_percent(current.get("cache_hit_percent")),
        "ttft": format_duration(current.get("ttft_ms")),
        "tps": format_rate(current.get("tps")),
        "latency": format_duration(current.get("latency_ms")),
        "context": format_context(current),
    }


def run_gui(root: str, interval: float = 1.0) -> int:
    """Start the optional PySide6 app, with a clear dependency error."""

    if importlib.util.find_spec("PySide6") is None:
        raise GuiUnavailableError("PySide6 is not installed; install the optional 'gui' dependency first")
    from .qt_app import run

    return run(root, interval)
