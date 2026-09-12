import unittest

from tokenwatch.models import Usage, parse_timestamp


class UsageTests(unittest.TestCase):
    def test_supports_rollout_field_names(self):
        usage = Usage.from_mapping(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "cache_write_input_tokens": 5,
                "output_tokens": 20,
                "reasoning_output_tokens": 3,
                "total_tokens": 120,
            }
        )
        self.assertEqual(usage.input_tokens, 100)
        self.assertEqual(usage.cached_tokens, 40)
        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.total_tokens, 120)

    def test_parses_iso_and_epoch_timestamps(self):
        self.assertIsNotNone(parse_timestamp("2026-01-01T00:00:00Z"))
        self.assertIsNotNone(parse_timestamp(1767225600))

