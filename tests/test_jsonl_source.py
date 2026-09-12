import json
import tempfile
import unittest
from pathlib import Path

from tokenwatch.sources.jsonl import RolloutJsonlSource


class RolloutSourceTests(unittest.TestCase):
    def test_normalizes_usage_turn_and_tool_events_without_retaining_body(self):
        records = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {"session_id": "s1", "cwd": "/tmp"},
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "t1", "started_at": "2026-01-01T00:00:01Z", "model_context_window": 1000},
            },
            {
                "timestamp": "2026-01-01T00:00:02Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20, "total_tokens": 120},
                        "model_context_window": 1000,
                    },
                    "rate_limits": {"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 1767225900}}}},
                },
            },
            {
                "timestamp": "2026-01-01T00:00:03Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]},
            },
            {
                "timestamp": "2026-01-01T00:00:04Z",
                "type": "response_item",
                "payload": {"type": "custom_tool_call", "id": "c1", "name": "exec", "input": "echo ok"},
            },
            {
                "timestamp": "2026-01-01T00:00:05Z",
                "type": "response_item",
                "payload": {"type": "custom_tool_call_output", "id": "o1", "output": [{"type": "input_text", "text": "ok"}]},
            },
            {
                "timestamp": "2026-01-01T00:00:06Z",
                "type": "event_msg",
                "payload": {"type": "task_complete"},
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout-test.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            events = list(RolloutJsonlSource(path).events())

        kinds = [event.kind for event in events]
        self.assertIn("usage", kinds)
        self.assertIn("tool_call", kinds)
        self.assertIn("tool_result", kinds)
        usage = next(event for event in events if event.kind == "usage")
        self.assertEqual(usage.turn_id, "t1")
        self.assertEqual(usage.usage.cached_tokens, 40)
        self.assertEqual(usage.quotas[0].window_duration_minutes, 300)

