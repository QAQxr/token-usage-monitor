"""Turn and Session aggregation over normalized events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import ceil
from typing import Any, Iterable, Mapping

from .models import Distribution, NormalizedEvent, QualityValue, QuotaWindow, Usage


def estimate_visible_tokens(chars: int) -> int | None:
    """Return a clearly-labelled rough estimate for visible text only."""

    if chars <= 0:
        return None
    return max(1, ceil(chars / 4))


@dataclass(frozen=True)
class PriceTable:
    """Optional API-style price table, in USD per million tokens."""

    input_per_million: float
    cached_input_per_million: float
    output_per_million: float

    def cost(self, usage: Usage) -> float:
        uncached = max(usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens, 0)
        return (
            uncached * self.input_per_million
            + usage.cached_tokens * self.cached_input_per_million
            + usage.output_tokens * self.output_per_million
        ) / 1_000_000


@dataclass
class TurnAggregate:
    session_id: str
    turn_id: str
    usage: Usage = field(default_factory=Usage)
    request_count: int = 0
    user_message_count: int = 0
    tool_call_count: int = 0
    tool_result_count: int = 0
    user_chars: int = 0
    tool_call_chars: int = 0
    tool_result_chars: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    first_output_at: datetime | None = None
    context_window: int | None = None
    quotas: tuple[QuotaWindow, ...] = ()

    def apply(self, event: NormalizedEvent) -> None:
        if event.kind == "turn_started":
            self.started_at = event.started_at or event.timestamp or self.started_at
            self.context_window = event.context_window or self.context_window
        elif event.kind == "turn_completed":
            self.completed_at = event.completed_at or event.timestamp or self.completed_at
        elif event.kind == "usage":
            if event.usage is not None:
                self.usage = self.usage + event.usage
                self.request_count += 1
            self.context_window = event.context_window or self.context_window
            if event.quotas:
                self.quotas = event.quotas
        elif event.kind == "user_message":
            self.user_message_count += 1
            self.user_chars += event.visible_text_chars
        elif event.kind == "tool_call":
            self.tool_call_count += 1
            self.tool_call_chars += event.visible_text_chars
        elif event.kind == "tool_result":
            self.tool_result_count += 1
            self.tool_result_chars += event.visible_text_chars
        elif event.kind == "assistant_delta" and self.first_output_at is None:
            self.first_output_at = event.timestamp

    def snapshot(self, prices: PriceTable | None = None) -> dict[str, Any]:
        cache_hit = None
        if self.usage.input_tokens:
            cache_hit = self.usage.cached_tokens / self.usage.input_tokens * 100

        latency_ms = _duration_ms(self.started_at, self.completed_at)
        ttft_ms = _duration_ms(self.started_at, self.first_output_at)
        generation_ms = _duration_ms(self.first_output_at, self.completed_at)
        tps = None
        if generation_ms and generation_ms > 0 and self.usage.output_tokens:
            tps = self.usage.output_tokens / (generation_ms / 1000)

        distribution = Distribution(
            user=QualityValue(
                estimate_visible_tokens(self.user_chars),
                "estimated" if self.user_chars else "unknown",
                "visible-message-length/4",
            ),
            output=QualityValue(self.usage.output_tokens, "exact", "last_token_usage.output_tokens"),
            tool_call=QualityValue(
                estimate_visible_tokens(self.tool_call_chars),
                "estimated" if self.tool_call_chars else "unknown",
                "visible-message-length/4",
            ),
            tool_result=QualityValue(
                estimate_visible_tokens(self.tool_result_chars),
                "estimated" if self.tool_result_chars else "unknown",
                "visible-message-length/4",
            ),
        )

        return {
            "scope": "turn",
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "request_count": self.request_count,
            "user_message_count": self.user_message_count,
            "tool_call_count": self.tool_call_count,
            "tool_result_count": self.tool_result_count,
            "total_tokens": self.usage.total_tokens,
            "input_tokens": self.usage.input_tokens,
            "cached_tokens": self.usage.cached_tokens,
            "output_tokens": self.usage.output_tokens,
            "cache_hit_percent": cache_hit,
            "ttft_ms": ttft_ms,
            "tps": tps,
            "latency_ms": latency_ms,
            "cost_usd": prices.cost(self.usage) if prices else None,
            "cost_quality": "exact-with-explicit-price-table" if prices else "unknown",
            "context_window": self.context_window,
            "distribution": _distribution_dict(distribution),
            "quotas": _quota_dict(self.quotas),
        }


class MetricsStore:
    """Incremental, deduplicated store for one or more sessions."""

    def __init__(self, prices: PriceTable | None = None):
        self.prices = prices
        self.sessions: dict[str, list[str]] = {}
        self.turns: dict[tuple[str, str], TurnAggregate] = {}
        self.applied_event_ids: set[str] = set()
        self.latest_quotas: dict[str, tuple[QuotaWindow, ...]] = {}

    def apply(self, event: NormalizedEvent) -> None:
        if event.event_id in self.applied_event_ids:
            return
        self.applied_event_ids.add(event.event_id)
        if event.quotas:
            self.latest_quotas[event.session_id] = event.quotas
        if event.kind == "session_started":
            self.sessions.setdefault(event.session_id, [])
            return
        if not event.turn_id:
            return
        key = (event.session_id, event.turn_id)
        if key not in self.turns:
            self.turns[key] = TurnAggregate(event.session_id, event.turn_id)
            self.sessions.setdefault(event.session_id, []).append(event.turn_id)
        self.turns[key].apply(event)

    def apply_all(self, events: Iterable[NormalizedEvent]) -> None:
        for event in events:
            self.apply(event)

    def turn_snapshot(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        turn = self.turns.get((session_id, turn_id))
        return turn.snapshot(self.prices) if turn else None

    def session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        turn_ids = self.sessions.get(session_id)
        if turn_ids is None:
            return None
        turns = [self.turns[(session_id, turn_id)] for turn_id in turn_ids if (session_id, turn_id) in self.turns]
        if not turns:
            return {
                "scope": "session",
                "session_id": session_id,
                "turn_count": 0,
                "request_count": 0,
                "total_tokens": 0,
                "input_tokens": 0,
                "cached_tokens": 0,
                "output_tokens": 0,
                "cache_hit_percent": None,
                "ttft_ms": None,
                "tps": None,
                "latency_ms": None,
                "cost_usd": None,
                "cost_quality": "unknown",
                "distribution": _distribution_dict(Distribution()),
                "quotas": _quota_dict(self.latest_quotas.get(session_id, ())),
            }

        usage = Usage()
        request_count = 0
        user_messages = tool_calls = tool_results = 0
        user_chars = tool_call_chars = tool_result_chars = 0
        started = min((turn.started_at for turn in turns if turn.started_at), default=None)
        completed = max((turn.completed_at for turn in turns if turn.completed_at), default=None)
        first_output = min((turn.first_output_at for turn in turns if turn.first_output_at), default=None)
        context_window = max((turn.context_window for turn in turns if turn.context_window), default=None)
        for turn in turns:
            usage = usage + turn.usage
            request_count += turn.request_count
            user_messages += turn.user_message_count
            tool_calls += turn.tool_call_count
            tool_results += turn.tool_result_count
            user_chars += turn.user_chars
            tool_call_chars += turn.tool_call_chars
            tool_result_chars += turn.tool_result_chars

        cache_hit = usage.cached_tokens / usage.input_tokens * 100 if usage.input_tokens else None
        latency_ms = _duration_ms(started, completed)
        ttft_ms = _duration_ms(started, first_output)
        generation_ms = _duration_ms(first_output, completed)
        tps = usage.output_tokens / (generation_ms / 1000) if generation_ms and usage.output_tokens else None
        distribution = Distribution(
            user=QualityValue(estimate_visible_tokens(user_chars), "estimated" if user_chars else "unknown", "visible-message-length/4"),
            output=QualityValue(usage.output_tokens, "exact", "last_token_usage.output_tokens"),
            tool_call=QualityValue(estimate_visible_tokens(tool_call_chars), "estimated" if tool_call_chars else "unknown", "visible-message-length/4"),
            tool_result=QualityValue(estimate_visible_tokens(tool_result_chars), "estimated" if tool_result_chars else "unknown", "visible-message-length/4"),
        )
        return {
            "scope": "session",
            "session_id": session_id,
            "turn_count": len(turns),
            "request_count": request_count,
            "user_message_count": user_messages,
            "tool_call_count": tool_calls,
            "tool_result_count": tool_results,
            "total_tokens": usage.total_tokens,
            "input_tokens": usage.input_tokens,
            "cached_tokens": usage.cached_tokens,
            "output_tokens": usage.output_tokens,
            "cache_hit_percent": cache_hit,
            "ttft_ms": ttft_ms,
            "tps": tps,
            "latency_ms": latency_ms,
            "cost_usd": self.prices.cost(usage) if self.prices else None,
            "cost_quality": "exact-with-explicit-price-table" if self.prices else "unknown",
            "context_window": context_window,
            "distribution": _distribution_dict(distribution),
            "quotas": _quota_dict(self.latest_quotas.get(session_id, ())),
        }

    def snapshot(self, session_id: str | None = None) -> dict[str, Any]:
        session_ids = [session_id] if session_id else list(self.sessions)
        return {
            "sessions": [self.session_snapshot(item) for item in session_ids if self.session_snapshot(item)],
            "turns": [
                self.turn_snapshot(item[0], item[1])
                for item in self.turns
                if session_id is None or item[0] == session_id
            ],
            "event_count": len(self.applied_event_ids),
        }


def _duration_ms(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return max((end - start).total_seconds() * 1000, 0)


def _distribution_dict(value: Distribution) -> dict[str, Any]:
    return {
        key: {"tokens": item.value, "quality": item.quality, "source": item.source}
        for key, item in {
            "user": value.user,
            "output": value.output,
            "tool_call": value.tool_call,
            "tool_result": value.tool_result,
        }.items()
    }


def _quota_dict(values: Iterable[QuotaWindow]) -> list[dict[str, Any]]:
    return [
        {
            "limit_id": item.limit_id,
            "limit_name": item.limit_name,
            "used_percent": item.used_percent,
            "window_duration_minutes": item.window_duration_minutes,
            "resets_at": item.resets_at.isoformat() if item.resets_at else None,
        }
        for item in values
    ]
