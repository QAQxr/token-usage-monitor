import tempfile
import unittest
from pathlib import Path

from tokenwatch.metrics import MetricsStore
from tokenwatch.monitor import SnapshotRefresher, latest_scope


class MonitorRefreshTests(unittest.TestCase):
    def test_reports_missing_rollout_without_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            refresher = SnapshotRefresher(directory, loader=lambda root: (None, MetricsStore()))
            state = refresher.refresh()

        self.assertEqual(state.status, "no_data")
        self.assertIn("No Codex rollout", state.message)

    def test_reports_active_and_idle_from_file_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout-test.jsonl"
            path.write_text("", encoding="utf-8")
            snapshot = {"sessions": [{"session_id": "s1"}], "turns": [{"turn_id": "t1"}]}

            class FakeStore:
                def snapshot(self):
                    return snapshot

            refresher = SnapshotRefresher(
                directory,
                loader=lambda root: (path, FakeStore()),
                active_window_seconds=10,
                clock=lambda: path.stat().st_mtime + 5,
            )
            self.assertEqual(refresher.refresh().status, "active")

            idle = SnapshotRefresher(
                directory,
                loader=lambda root: (path, FakeStore()),
                active_window_seconds=10,
                clock=lambda: path.stat().st_mtime + 11,
            ).refresh()
            self.assertEqual(idle.status, "idle")
            self.assertIn("no active session", idle.message.lower())

    def test_reports_parser_errors_as_state(self):
        def broken_loader(root):
            raise ValueError("bad json")

        state = SnapshotRefresher("/tmp", loader=broken_loader).refresh()
        self.assertEqual(state.status, "error")
        self.assertIn("ValueError", state.error)

    def test_latest_scope_selects_newest_item(self):
        snapshot = {"sessions": [{"session_id": "old"}, {"session_id": "new"}], "turns": []}
        self.assertEqual(latest_scope(snapshot, "session")["session_id"], "new")
        self.assertIsNone(latest_scope(snapshot, "turn"))
