import json
import tempfile
import unittest
from pathlib import Path

from tokenwatch.metrics import MetricsStore, PriceTable
from tokenwatch.models import NormalizedEvent, Usage
from tokenwatch.sources.jsonl import RolloutJsonlSource


class MetricsTests(unittest.TestCase):
    def _store(self):
        records = [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"session_id": "s1"}},
            {"timestamp": "2026-01-01T00:00:01Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1", "started_at": "2026-01-01T00:00:01Z", "model_context_window": 1000}},
            {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20, "total_tokens": 120}, "model_context_window": 1000}}},
            {"timestamp": "2026-01-01T00:00:03Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": "hello world"}]}},
            {"timestamp": "2026-01-01T00:00:04Z", "type": "response_item", "payload": {"type": "custom_tool_call", "input": "x" * 8}},
            {"timestamp": "2026-01-01T00:00:05Z", "type": "response_item", "payload": {"type": "custom_tool_call_output", "output": "y" * 8}},
            {"timestamp": "2026-01-01T00:00:06Z", "type": "event_msg", "payload": {"type": "task_complete"}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout-test.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            store = MetricsStore(PriceTable(1.0, 0.1, 2.0))
            store.apply_all(RolloutJsonlSource(path).events())
            return store

    def test_turn_and_session_metrics(self):
        store = self._store()
        turn = store.turn_snapshot("s1", "t1")
        session = store.session_snapshot("s1")
        self.assertEqual(turn["total_tokens"], 120)
        self.assertEqual(turn["input_tokens"], 100)
        self.assertEqual(turn["cached_tokens"], 40)
        self.assertEqual(turn["output_tokens"], 20)
        self.assertAlmostEqual(turn["cache_hit_percent"], 40.0)
        self.assertEqual(turn["latency_ms"], 5000.0)
        self.assertEqual(turn["ttft_ms"], None)
        self.assertEqual(turn["cost_usd"], 0.000104)
        self.assertEqual(session["turn_count"], 1)
        self.assertEqual(session["request_count"], 1)
        self.assertEqual(session["tool_call_count"], 1)
        self.assertEqual(session["tool_result_count"], 1)
        self.assertEqual(session["distribution"]["output"]["quality"], "exact")
        self.assertEqual(session["distribution"]["user"]["quality"], "estimated")

    def test_duplicate_event_is_ignored(self):
        event = NormalizedEvent(
            event_id="same",
            source="test",
            session_id="s1",
            timestamp=None,
            kind="usage",
            turn_id="t1",
            usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12),
        )
        store = MetricsStore()
        store.apply(event)
        store.apply(event)
        self.assertEqual(store.session_snapshot("s1")["request_count"], 1)
