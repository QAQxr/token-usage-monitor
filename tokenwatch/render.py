"""Fixed-width TokenWatch text renderer."""

from __future__ import annotations

import html
from typing import Iterable

from .codex import UsageSnapshot


INNER_WIDTH = 30
BAR_WIDTH = 14
NUMBER_COLOR = "#111827"


def _trim_decimal(value: float, places: int) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def compact_count(value: int | float | None, max_width: int | None = None) -> str:
    if value is None:
        return "—"
    number = float(value)
    absolute = abs(number)
    if absolute >= 1_000_000_000:
        text = _trim_decimal(number / 1_000_000_000, 2 if absolute < 10_000_000_000 else 1) + "B"
    elif absolute >= 1_000_000:
        text = _trim_decimal(number / 1_000_000, 2 if absolute < 10_000_000 else 1) + "M"
    elif absolute >= 1_000:
        text = _trim_decimal(number / 1_000, 2 if absolute < 10_000 else 1) + "K"
    else:
        text = str(int(number))
    if max_width is not None and len(text) > max_width and absolute >= 1_000:
        if absolute >= 1_000_000_000:
            text = str(round(number / 1_000_000_000)) + "B"
        elif absolute >= 1_000_000:
            text = str(round(number / 1_000_000)) + "M"
        else:
            text = str(round(number / 1_000)) + "K"
    return text


def percent(value: float | None, placeholder: str = "—") -> str:
    if value is None:
        return placeholder
    return f"{max(0.0, min(100.0, float(value))):.2f}%"


def rate_percent(value: float | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    return f"{max(0.0, min(100.0, number)):.2f}%"


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else 100.0 * numerator / denominator


def _bar(value: float | None) -> str:
    if value is None:
        return "░" * BAR_WIDTH
    filled = round(max(0.0, min(100.0, value)) / 100.0 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _fit(text: str, width: int = INNER_WIDTH) -> str:
    return text[:width].ljust(width)


def _bar_line(label: str, value: float | None, placeholder: str = "—") -> str:
    value_text = percent(value, placeholder)
    if len(value_text) > 6:
        # Keep the full 100.00% inside the fixed-width line.
        return _fit(f" {label:<7} {_bar(value)}{value_text:>7}")
    return _fit(f" {label:<7} {_bar(value)} {value_text:>6}")


def _styled_line(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """Add dark/bold Pango spans without changing the visible fixed width."""
    spans = tuple(spans)
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(html.escape(text[cursor:start], quote=False))
        pieces.append(
            f'<span foreground="{NUMBER_COLOR}" weight="bold">'
            f"{html.escape(text[start:end], quote=False)}</span>"
        )
        cursor = end
    if not spans:
        return html.escape(text, quote=False)
    pieces.append(html.escape(text[cursor:], quote=False))
    return "".join(pieces)


def _field_line(
    fields: Iterable[tuple[int, int, str, str]],
) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Place left/right aligned dynamic fields and return their visible spans."""
    chars = [" "] * INNER_WIDTH
    spans: list[tuple[int, int]] = []
    for start, end, value, alignment in fields:
        width = end - start
        value = value[-width:] if alignment == "right" else value[:width]
        offset = end - len(value) if alignment == "right" else start
        chars[offset : offset + len(value)] = list(value)
        spans.append((offset, offset + len(value)))
    return "".join(chars), tuple(spans)


def _data_line(snapshot: UsageSnapshot) -> str:
    line, _ = _field_line(
        (
            (1, 8, compact_count(snapshot.total.total_tokens), "left"),
            (9, 15, str(snapshot.request_count) if snapshot.request_count else "—", "left"),
            (16, 25, compact_count(snapshot.total.input_tokens), "left"),
            (26, 30, compact_count(snapshot.total.output_tokens, max_width=4), "left"),
        )
    )
    return line


def _data_markup(snapshot: UsageSnapshot) -> str:
    line, spans = _field_line(
        (
            (1, 8, compact_count(snapshot.total.total_tokens), "left"),
            (9, 15, str(snapshot.request_count) if snapshot.request_count else "—", "left"),
            (16, 25, compact_count(snapshot.total.input_tokens), "left"),
            (26, 30, compact_count(snapshot.total.output_tokens, max_width=4), "left"),
        )
    )
    return _styled_line(line, spans)


def render_lines(snapshot: UsageSnapshot) -> tuple[str, ...]:
    session_hit = (
        _ratio(snapshot.total.cached_input_tokens, snapshot.total.input_tokens)
        if snapshot.cache_available
        else None
    )
    last_hit = _ratio(snapshot.last.cached_input_tokens, snapshot.last.input_tokens) if snapshot.cache_available else None
    context = _ratio(snapshot.last.input_tokens, snapshot.context_window or 0)
    header_right = f"{percent(last_hit, '-'):>5} HIT "
    header_left = " ▼ TokenWatch"
    header = header_left + " " * max(1, INNER_WIDTH - len(header_left) - len(header_right)) + header_right
    context_values = f"{compact_count(snapshot.last.input_tokens)} / {compact_count(snapshot.context_window)}"
    bottom, _ = _field_line(
        (
            (3, 10, rate_percent(snapshot.primary_used_percent), "right"),
            (22, 29, rate_percent(snapshot.secondary_used_percent), "right"),
        )
    )
    bottom = bottom[:1] + "5h" + bottom[3:20] + "7d" + bottom[22:]
    return (
        "╭" + "─" * INNER_WIDTH + "╮",
        "│" + _fit(header) + "│",
        "├" + "─" * INNER_WIDTH + "┤",
        "│" + _data_line(snapshot) + "│",
        "│" + _fit(" TOTAL   REQ    INPUT     OUT ") + "│",
        "│" + " " * INNER_WIDTH + "│",
        "│" + _bar_line("Session", session_hit, "-") + "│",
        "│" + _bar_line("Last", last_hit, "-") + "│",
        "│" + _bar_line("Context", context) + "│",
        "│" + _fit(context_values.rjust(INNER_WIDTH)) + "│",
        "│" + _fit(bottom) + "│",
        "╰" + "─" * INNER_WIDTH + "╯",
    )


def _bar_markup(label: str, value: float | None, placeholder: str = "—") -> str:
    line = _bar_line(label, value, placeholder)
    value_text = percent(value, placeholder)
    if len(value_text) > 6:
        prefix = f" {label:<7} {_bar(value)}"
        start = len(prefix) + max(0, 7 - len(value_text))
    else:
        prefix = f" {label:<7} {_bar(value)} "
        start = len(prefix) + max(0, 6 - len(value_text))
    return _styled_line(line, ((start, min(start + len(value_text), len(line))),))


def render_markup(snapshot: UsageSnapshot) -> str:
    """Render the same layout with dark/bold spans around dynamic numbers."""
    session_hit = (
        _ratio(snapshot.total.cached_input_tokens, snapshot.total.input_tokens)
        if snapshot.cache_available
        else None
    )
    last_hit = _ratio(snapshot.last.cached_input_tokens, snapshot.last.input_tokens) if snapshot.cache_available else None
    context = _ratio(snapshot.last.input_tokens, snapshot.context_window or 0)
    header_right = f"{percent(last_hit, '-'):>5} HIT "
    header_left = " ▼ TokenWatch"
    header = header_left + " " * max(1, INNER_WIDTH - len(header_left) - len(header_right)) + header_right
    header = _fit(header)
    header_value_start = header.rfind(percent(last_hit, "-"))

    context_total = compact_count(snapshot.last.input_tokens)
    context_window = compact_count(snapshot.context_window)
    context_line = f"{context_total} / {context_window}".rjust(INNER_WIDTH)
    context_spans = (
        (context_line.find(context_total), context_line.find(context_total) + len(context_total)),
        (context_line.rfind(context_window), context_line.rfind(context_window) + len(context_window)),
    )

    bottom, bottom_spans = _field_line(
        (
            (3, 10, rate_percent(snapshot.primary_used_percent), "right"),
            (22, 29, rate_percent(snapshot.secondary_used_percent), "right"),
        )
    )
    bottom = bottom[:1] + "5h" + bottom[3:20] + "7d" + bottom[22:]

    return "\n".join(
        (
            "╭" + "─" * INNER_WIDTH + "╮",
            "│" + _styled_line(header, ((header_value_start, header_value_start + len(percent(last_hit, "-"))),)) + "│",
            "├" + "─" * INNER_WIDTH + "┤",
            "│" + _data_markup(snapshot) + "│",
            "│" + _fit(" TOTAL   REQ    INPUT     OUT ") + "│",
            "│" + " " * INNER_WIDTH + "│",
            "│" + _bar_markup("Session", session_hit, "-") + "│",
            "│" + _bar_markup("Last", last_hit, "-") + "│",
            "│" + _bar_markup("Context", context) + "│",
            "│" + _styled_line(context_line, context_spans) + "│",
            "│" + _styled_line(bottom, bottom_spans) + "│",
            "╰" + "─" * INNER_WIDTH + "╯",
        )
    )


def render(snapshot: UsageSnapshot) -> str:
    return "\n".join(render_lines(snapshot))


def validate_layout(lines: Iterable[str]) -> None:
    values = tuple(lines)
    if len(values) != 12 or any(len(line) != INNER_WIDTH + 2 for line in values):
        raise ValueError("TokenWatch layout is not fixed-width")
