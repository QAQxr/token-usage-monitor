import json
import os
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tokenwatch.codex import (
    IncrementalRolloutReader,
    ProbeCandidate,
    SessionIndex,
    choose_thread_id,
)
from tokenwatch.app import _acquire_instance_lock
from tokenwatch.render import render, render_lines, render_markup, validate_layout


A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
C = "33333333-3333-4333-8333-333333333333"


def usage_record(total: int, last_input: int, request: int, primary: float) -> dict:
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total - 100,
                    "cached_input_tokens": total - 300,
                    "output_tokens": 100,
                    "total_tokens": total,
                },
                "last_token_usage": {
                    "input_tokens": last_input,
                    "cached_input_tokens": last_input // 2,
                    "output_tokens": 20,
                    "total_tokens": last_input + 20,
                },
                "model_context_window": 1000,
            },
            "rate_limits": {
                "primary": {"used_percent": primary},
                "secondary": {"used_percent": 2},
            },
        },
    }


def write_rollout(root: Path, thread_id: str, total: int) -> Path:
    path = root / "2026" / "09" / f"rollout-test-{thread_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "session_meta", "payload": {"id": thread_id}},
        usage_record(total, 400, 1, float(total // 100)),
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


class CompanionDataTests(unittest.TestCase):
    def test_thread_index_and_reader_stay_on_the_selected_rollout_a_b_c_a(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {thread: write_rollout(root, thread, total) for thread, total in ((A, 111), (B, 222), (C, 333))}
            index = SessionIndex(root)
            reader = IncrementalRolloutReader()
            observed = []
            for thread in (A, B, C, A):
                selected = index.resolve(thread)
                self.assertEqual(selected, paths[thread])
                snapshot = reader.switch(selected)
                self.assertIsNotNone(snapshot)
                observed.append(snapshot.total.total_tokens)
            self.assertEqual(observed, [111, 222, 333, 111])

    def test_same_thread_uses_the_newest_rollout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "2026" / "09" / "rollout-old.jsonl"
            new = root / "2026" / "09" / "rollout-new.jsonl"
            old.parent.mkdir(parents=True)
            record = json.dumps({"type": "session_meta", "payload": {"id": A}}) + "\n"
            old.write_text(record, encoding="utf-8")
            new.write_text(record, encoding="utf-8")
            newer = old.stat().st_mtime_ns + 1_000_000
            os.utime(new, ns=(newer, newer))
            self.assertEqual(SessionIndex(root).resolve(A), new)

    def test_incremental_reader_consumes_an_appended_token_count_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{A}.jsonl"
            path.write_text(json.dumps(usage_record(100, 40, 1, 1)) + "\n", encoding="utf-8")
            reader = IncrementalRolloutReader()
            first = reader.switch(path)
            self.assertEqual((first.request_count, first.total.total_tokens), (1, 100))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(usage_record(200, 80, 2, 2)) + "\n")
            second = reader.poll()
            self.assertEqual((second.request_count, second.total.total_tokens), (2, 200))
            third = reader.poll()
            self.assertEqual((third.request_count, third.total.total_tokens), (2, 200))

    def test_probe_selection_rejects_equal_best_candidates(self):
        self.assertEqual(
            choose_thread_id([ProbeCandidate(A, "active.href", 960), ProbeCandidate(B, "dom.href", 520)]),
            A,
        )
        self.assertIsNone(choose_thread_id([ProbeCandidate(A, "history.state", 940), ProbeCandidate(B, "history.state", 940)]))

    def test_fixed_text_layout_has_no_extra_normal_state_fields(self):
        path_snapshot = None
        with tempfile.TemporaryDirectory() as directory:
            path = write_rollout(Path(directory), A, 3892679)
            reader = IncrementalRolloutReader()
            path_snapshot = reader.switch(path)
        lines = render_lines(path_snapshot)
        validate_layout(lines)
        self.assertEqual(len(lines), 12)
        self.assertIn("TOTAL", lines[4])
        self.assertIn("REQ", lines[4])
        self.assertIn("Session", lines[6])
        self.assertIn("Last", lines[7])
        self.assertIn("Context", lines[8])
        self.assertIn("5h", lines[10])
        self.assertIn("7d", lines[10])
        self.assertNotIn(A, render(path_snapshot))

    def test_display_precision_columns_and_emphasis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_rollout(Path(directory), A, 3892679)
            snapshot = IncrementalRolloutReader().switch(path)

        lines = render_lines(snapshot)
        self.assertIn("50.00% HIT", lines[1])
        self.assertIn("99.99%", lines[6])
        self.assertIn("50.00%", lines[7])
        self.assertIn("5h100.00%", lines[10])
        self.assertIn("7d  2.00%", lines[10])

        full_usage_lines = render_lines(replace(snapshot, primary_used_percent=100, secondary_used_percent=100))
        self.assertIn("100.00%", full_usage_lines[10])
        self.assertNotIn("5h00.00%", full_usage_lines[10])
        self.assertNotIn("7d00.00%", full_usage_lines[10])

        # Each dynamic value starts under the matching column heading.
        self.assertEqual(lines[3].index("3.89M"), lines[4].index("TOTAL"))
        self.assertEqual(lines[3].index("1"), lines[4].index("REQ"))
        self.assertEqual(lines[3].rindex("3.89M"), lines[4].index("INPUT"))
        self.assertEqual(lines[3].rindex("100"), lines[4].index("OUT"))

        markup = render_markup(snapshot)
        visible = re.sub(r"<[^>]+>", "", markup)
        self.assertEqual(visible, render(snapshot))
        self.assertIn('foreground="#111827"', markup)
        self.assertIn('weight="bold"', markup)

    def test_non_work_view_uses_dash_for_cache_but_keeps_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_rollout(Path(directory), A, 3892679)
            snapshot = IncrementalRolloutReader().switch(path)

        non_work = replace(snapshot, cache_available=False)
        lines = render_lines(non_work)
        self.assertIn("- HIT", lines[1])
        self.assertIn("-", lines[6])
        self.assertIn("-", lines[7])
        self.assertIn("5h100.00%", lines[10])
        self.assertIn("7d  2.00%", lines[10])
        self.assertEqual(re.sub(r"<[^>]+>", "", render_markup(non_work)), render(non_work))

    def test_companion_instance_lock_rejects_a_second_process(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("XDG_RUNTIME_DIR")
            os.environ["XDG_RUNTIME_DIR"] = directory
            try:
                first = _acquire_instance_lock()
                self.assertIsNotNone(first)
                second = _acquire_instance_lock()
                self.assertIsNone(second)
                first.close()
            finally:
                if previous is None:
                    os.environ.pop("XDG_RUNTIME_DIR", None)
                else:
                    os.environ["XDG_RUNTIME_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
