"""Tests for the parser, against real output of /usage.

Run: python3 -m unittest -v
After a Claude Code update: add the new output here as another sample.
"""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from claude_usage import UsageError, parse

AMS = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 9, 11, 18, 30, tzinfo=AMS)

# Claude Code 2.1.268: "resets <date> at <time>"
WITH_AT = """You are currently using your subscription to power your Claude Code usage

Current session: 14% used · resets Sep 11 at 10:10pm (Europe/Amsterdam)
Current week (all models): 50% used · resets Sep 15 at 12am (Europe/Amsterdam)

What's contributing to your limits usage?
"""

# Claude Code 2.1.267: a comma where 2.1.268 writes "at"
WITH_COMMA = """You are currently using your subscription to power your Claude Code usage

Current session: 17% used · resets Sep 11, 10:10pm (Europe/Amsterdam)
Current week (all models): 50% used · resets Sep 15, 12am (Europe/Amsterdam)
"""

# What /usage prints without a subscription login
NOT_LOGGED_IN = """Total cost:            $0.0000
Total duration (API):  0s
Usage:                 0 input, 0 output, 0 cache read, 0 cache write
"""


class ParseTests(unittest.TestCase):
    def test_reset_written_with_at(self):
        r = parse(WITH_AT, NOW)
        self.assertEqual((r["current"], r["weekly"]), (14, 50))
        self.assertEqual(r["current_resets_at"], "2026-09-11T22:10:00+02:00")
        self.assertEqual(r["weekly_resets_at"], "2026-09-15T00:00:00+02:00")

    def test_reset_written_with_comma(self):
        r = parse(WITH_COMMA, NOW)
        self.assertEqual((r["current"], r["weekly"]), (17, 50))
        self.assertEqual(r["current_resets_at"], "2026-09-11T22:10:00+02:00")
        self.assertEqual(r["weekly_resets_at"], "2026-09-15T00:00:00+02:00")

    def test_year_rollover(self):
        text = WITH_AT.replace("Sep 15 at 12am", "Jan 2 at 9am")
        r = parse(text, datetime(2026, 12, 30, 12, 0, tzinfo=AMS))
        self.assertEqual(r["weekly_resets_at"], "2027-01-02T09:00:00+01:00")

    def test_time_only_and_no_reset(self):
        text = ("Current session: 0% used\n"
                "Current week (all models): 3.5% used · resets 10pm (Europe/Amsterdam)\n")
        r = parse(text, NOW)
        self.assertEqual(r["current"], 0)
        self.assertIsNone(r["current_resets_at"])
        self.assertEqual(r["weekly"], 3.5)
        self.assertEqual(r["weekly_resets_at"], "2026-09-11T22:00:00+02:00")

    def test_other_weekly_lines_are_ignored(self):
        text = WITH_AT.replace(
            "Current week (all models)", "Current week (Sonnet only): 80% used\nCurrent week (all models)")
        self.assertEqual(parse(text, NOW)["weekly"], 50)

    def test_not_logged_in_is_an_error(self):
        with self.assertRaises(UsageError):
            parse(NOT_LOGGED_IN, NOW)


if __name__ == "__main__":
    unittest.main()
