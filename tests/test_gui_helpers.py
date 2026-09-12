import unittest

from tokenwatch.gui import format_context, format_duration, format_number, format_percent, format_rate, scope_values


class GuiHelperTests(unittest.TestCase):
    def test_formats_values_and_unknowns(self):
        self.assertEqual(format_number(1234567), "1,234,567")
        self.assertEqual(format_percent(None), "—")
        self.assertEqual(format_duration(1250), "1.25s")
        self.assertEqual(format_rate(12.5), "12.5 tok/s")
        self.assertEqual(format_context({"total_tokens": 120, "context_window": 1000}), "120 / 1,000")

    def test_scope_values_are_display_ready(self):
        snapshot = {
            "sessions": [],
            "turns": [
                {
                    "turn_id": "t1",
                    "total_tokens": 120,
                    "input_tokens": 100,
                    "cached_tokens": 40,
                    "output_tokens": 20,
                    "cache_hit_percent": 40.0,
                    "ttft_ms": None,
                    "tps": 2.0,
                    "latency_ms": 1500,
                    "context_window": 1000,
                }
            ],
        }
        values = scope_values(snapshot, "turn")
        self.assertEqual(values["total"], "120")
        self.assertEqual(values["cache"], "40.0%")
        self.assertEqual(values["ttft"], "—")
        self.assertEqual(values["latency"], "1.50s")

    def test_scope_values_handle_empty_snapshot(self):
        values = scope_values({"sessions": [], "turns": []}, "session")
        self.assertTrue(all(value == "—" for value in values.values()))
