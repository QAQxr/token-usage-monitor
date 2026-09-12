"""Adapter for Codex rollout JSONL records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from ..models import NormalizedEvent, QuotaWindow, Usage, parse_timestamp


def _text_chars(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_text_chars(item) for item in value)
    if isinstance(value, dict):
        return sum(_text_chars(item) for key, item in value.items() if key in {"text", "content", "input", "output"})
    return 0


def _quotas(payload: Mapping[str, Any]) -> tuple[QuotaWindow, ...]:
    raw = payload.get("rate_limits") or payload.get("rateLimits") or {}
    if not isinstance(raw, Mapping):
        return ()
    buckets = raw.get("rateLimitsByLimitId") or raw.get("rate_limits_by_limit_id")
    if not isinstance(buckets, Mapping):
        buckets = {raw.get("limitId", "codex"): raw}
    result: list[QuotaWindow] = []
    for limit_id, bucket in buckets.items():
        if not isinstance(bucket, Mapping):
            continue
        primary = bucket.get("primary") or {}
        if not isinstance(primary, Mapping):
            continue
        result.append(
            QuotaWindow(
                limit_id=str(limit_id),
                used_percent=(float(primary["usedPercent"]) if "usedPercent" in primary else primary.get("used_percent")),
                window_duration_minutes=(
                    int(primary["windowDurationMins"])
                    if "windowDurationMins" in primary
                    else primary.get("window_duration_minutes", primary.get("window_minutes"))
                ),
                resets_at=parse_timestamp(primary.get("resetsAt", primary.get("resets_at"))),
                limit_name=bucket.get("limitName", bucket.get("limit_name")),
            )
        )
    return tuple(result)


class RolloutJsonlSource:
    """Parse a rollout file while retaining only normalized metadata."""

    source_name = "rollout-jsonl"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def records(self) -> Iterator[dict[str, Any]]:
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value

    def events(self) -> Iterator[NormalizedEvent]:
        session_id = self.path.stem
        current_turn: str | None = None
        current_turn_started: Any = None

        for ordinal, record in enumerate(self.records()):
            timestamp = parse_timestamp(record.get("timestamp"))
            record_type = record.get("type")
            payload = record.get("payload") or {}
            if not isinstance(payload, Mapping):
                continue

            if record_type == "session_meta":
                session_id = str(payload.get("session_id") or payload.get("id") or session_id)
                yield NormalizedEvent(
                    event_id=f"{self.source_name}:{ordinal}",
                    source=self.source_name,
                    session_id=session_id,
                    timestamp=timestamp,
                    kind="session_started",
                    metadata={"cwd": payload.get("cwd"), "model_provider": payload.get("model_provider")},
                )
                continue

            if record_type == "event_msg":
                event_type = payload.get("type")
                if event_type == "task_started":
                    current_turn = str(payload.get("turn_id")) if payload.get("turn_id") else None
                    current_turn_started = parse_timestamp(payload.get("started_at")) or timestamp
                    yield NormalizedEvent(
                        event_id=f"{self.source_name}:{ordinal}",
                        source=self.source_name,
                        session_id=session_id,
                        timestamp=timestamp,
                        kind="turn_started",
                        turn_id=current_turn,
                        started_at=current_turn_started,
                        context_window=payload.get("model_context_window"),
                    )
                    continue

                if event_type == "task_complete":
                    yield NormalizedEvent(
                        event_id=f"{self.source_name}:{ordinal}",
                        source=self.source_name,
                        session_id=session_id,
                        timestamp=timestamp,
                        kind="turn_completed",
                        turn_id=current_turn,
                        started_at=current_turn_started,
                        completed_at=timestamp,
                    )
                    current_turn = None
                    current_turn_started = None
                    continue

                if event_type == "token_count":
                    info = payload.get("info") or {}
                    if not isinstance(info, Mapping):
                        continue
                    usage = Usage.from_mapping(info.get("last_token_usage"))
                    yield NormalizedEvent(
                        event_id=f"{self.source_name}:{ordinal}",
                        source=self.source_name,
                        session_id=session_id,
                        timestamp=timestamp,
                        kind="usage",
                        turn_id=current_turn,
                        usage=usage,
                        context_window=info.get("model_context_window"),
                        quotas=_quotas(payload),
                        metadata={"total_usage": info.get("total_token_usage")},
                    )
                    continue

                if event_type in {"item_started", "item_completed"}:
                    item = payload.get("item") or {}
                    if not isinstance(item, Mapping):
                        continue
                    item_type = str(item.get("type") or "")
                    kind = "item_started" if event_type == "item_started" else "item_completed"
                    yield NormalizedEvent(
                        event_id=f"{self.source_name}:{ordinal}",
                        source=self.source_name,
                        session_id=session_id,
                        timestamp=timestamp,
                        kind=kind,
                        turn_id=payload.get("turn_id") or current_turn,
                        item_id=item.get("id"),
                        item_type=item_type,
                        started_at=parse_timestamp(payload.get("started_at_ms")),
                        completed_at=parse_timestamp(payload.get("completed_at_ms")),
                        visible_text_chars=_text_chars(item),
                    )
                    continue

            if record_type == "response_item":
                item_type = payload.get("type")
                role = payload.get("role")
                if item_type == "message":
                    kind = "user_message" if role == "user" else "assistant_message"
                elif item_type == "custom_tool_call":
                    kind = "tool_call"
                elif item_type == "custom_tool_call_output":
                    kind = "tool_result"
                else:
                    continue
                yield NormalizedEvent(
                    event_id=f"{self.source_name}:{ordinal}",
                    source=self.source_name,
                    session_id=session_id,
                    timestamp=timestamp,
                    kind=kind,
                    turn_id=current_turn,
                    item_id=payload.get("id"),
                    item_type=str(item_type),
                    role=role,
                    visible_text_chars=_text_chars(payload),
                    metadata={"call_id": payload.get("call_id"), "name": payload.get("name")},
                )


def newest_rollout(root: str | Path) -> Path | None:
    candidates = list(Path(root).glob("**/rollout-*.jsonl"))
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None
