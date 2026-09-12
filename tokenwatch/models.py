"""Provider-neutral data models used by sources and metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp or Unix seconds/milliseconds without guessing."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _number(mapping: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "Usage | None":
        if not value:
            return None
        input_tokens = _number(value, "input_tokens", "prompt_tokens")
        cached_tokens = _number(value, "cached_input_tokens", "cached_tokens")
        output_tokens = _number(value, "output_tokens", "completion_tokens")
        total_tokens = _number(value, "total_tokens")
        if not total_tokens:
            total_tokens = input_tokens + output_tokens
        return cls(
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=_number(value, "cache_write_input_tokens", "cache_write_tokens"),
            output_tokens=output_tokens,
            reasoning_output_tokens=_number(value, "reasoning_output_tokens", "reasoning_tokens"),
            total_tokens=total_tokens,
        )

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class QuotaWindow:
    limit_id: str
    used_percent: float | None = None
    window_duration_minutes: int | None = None
    resets_at: datetime | None = None
    limit_name: str | None = None


@dataclass(frozen=True)
class QualityValue:
    value: int | float | None
    quality: str = "unknown"
    source: str = ""


@dataclass(frozen=True)
class Distribution:
    user: QualityValue = field(default_factory=lambda: QualityValue(None))
    output: QualityValue = field(default_factory=lambda: QualityValue(None))
    tool_call: QualityValue = field(default_factory=lambda: QualityValue(None))
    tool_result: QualityValue = field(default_factory=lambda: QualityValue(None))


@dataclass(frozen=True)
class NormalizedEvent:
    """Metadata-only event emitted by a source adapter."""

    event_id: str
    source: str
    session_id: str
    timestamp: datetime | None
    kind: str
    turn_id: str | None = None
    item_id: str | None = None
    item_type: str | None = None
    role: str | None = None
    usage: Usage | None = None
    context_window: int | None = None
    quotas: tuple[QuotaWindow, ...] = ()
    started_at: datetime | None = None
    completed_at: datetime | None = None
    visible_text_chars: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
