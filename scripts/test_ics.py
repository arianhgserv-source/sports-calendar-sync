"""Unit tests for the stdlib-only iCalendar builder."""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

# Make sure the sibling ics.py is importable no matter where unittest is run.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ics import build_calendar, escape_text, fold_line, make_uid  # noqa: E402


class FoldLineTests(unittest.TestCase):
    def test_short_line_unchanged(self):
        line = "SUMMARY:Hi"
        self.assertEqual(fold_line(line), line)
        self.assertNotIn("\r\n", line)

    def test_exactly_limit_is_unchanged(self):
        line = "X" * 75
        self.assertEqual(fold_line(line), line)
        self.assertNotIn("\r\n", fold_line(line))

    def test_one_over_limit_folds(self):
        out = fold_line("X" * 76)
        self.assertEqual(out, "X" * 75 + "\r\n " + "X")
        physical = out.split("\r\n")
        self.assertEqual(len(physical), 2)
        self.assertTrue(physical[1].startswith(" "))
        self.assertTrue(all(len(p.encode("utf-8")) <= 75 for p in physical))

    def test_uses_crlf_not_bare_lf(self):
        out = fold_line("X" * 300)
        self.assertIn("\r\n", out)
        for index, char in enumerate(out):
            if char == "\n":
                self.assertEqual(out[index - 1], "\r")

    def test_reconstruction_after_unfolding(self):
        line = "A" * 74 + "é" + "B" * 40
        out = fold_line(line)
        rebuilt = out.replace("\r\n ", "").replace("\r\n", "")
        self.assertEqual(rebuilt, line)

    def test_multibyte_character_is_never_split(self):
        # 74 ASCII octets + a 3-octet emoji would cross the 75-octet boundary;
        # the emoji must move whole onto the continuation line.
        line = "a" * 74 + "⚽" + "b" * 20
        out = fold_line(line)
        self.assertEqual(out.split("\r\n")[0], "a" * 74)
        self.assertTrue(out.split("\r\n")[1].startswith(" ⚽"))
        for physical in out.split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)
            # Each physical line must be valid UTF-8 on its own.
            physical.encode("utf-8").decode("utf-8")
        self.assertEqual(out.replace("\r\n ", ""), line)

    def test_no_physical_line_exceeds_limit_with_multibyte(self):
        out = fold_line(" clubs ⚽ " * 50)
        for physical in out.split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)

    def test_empty_input(self):
        self.assertEqual(fold_line(""), "")


class EscapeTextTests(unittest.TestCase):
    def test_backslash(self):
        self.assertEqual(escape_text(r"a\b"), r"a\\b")

    def test_semicolon(self):
        self.assertEqual(escape_text("a;b"), r"a\;b")

    def test_comma(self):
        self.assertEqual(escape_text("a,b"), r"a\,b")

    def test_newlines(self):
        self.assertEqual(escape_text("a\nb"), r"a\nb")
        self.assertEqual(escape_text("a\r\nb"), r"a\nb")
        self.assertEqual(escape_text("a\rb"), r"a\nb")

    def test_combined_and_escape_order(self):
        # The original backslash must be doubled before ';' and ',' are escaped.
        self.assertEqual(escape_text("A\\B;C,D\nE"), r"A\\B\;C\,D\nE")

    def test_empty_and_none(self):
        self.assertEqual(escape_text(""), "")
        self.assertEqual(escape_text(None), "")


class MakeUidTests(unittest.TestCase):
    def test_exact_value(self):
        self.assertEqual(make_uid("nba", "12345"), "nba-12345@sports.houissa.com")

    def test_stable_across_calls(self):
        self.assertEqual(make_uid("nfl", "7"), make_uid("nfl", "7"))

    def test_unique_per_game(self):
        self.assertNotEqual(make_uid("nba", "1"), make_uid("nba", "2"))
        self.assertNotEqual(make_uid("nba", "1"), make_uid("nfl", "1"))


class BuildCalendarTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 2, 15, 30, tzinfo=timezone(timedelta(hours=-5)))
        self.event = {
            "uid": make_uid("nba", "1"),
            "start": self.start,
            "duration_minutes": 150,
            "summary": "Team A vs Team B; playoffs, round 1",
            "description": "Line1\nLine2\\note",
            "location": "Arena; Section 3",
        }

    def test_crlf_line_endings(self):
        out = build_calendar([self.event])
        self.assertIn("\r\n", out)
        self.assertNotIn("\n", out.replace("\r\n", ""))
        self.assertTrue(out.endswith("\r\n"))

    def test_required_headers(self):
        out = build_calendar([self.event], name="My Sports")
        for header in (
            "BEGIN:VCALENDAR",
            "PRODID:",
            "VERSION:2.0",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "X-WR-CALNAME:My Sports",
            "X-WR-TIMEZONE:UTC",
            "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
            "X-PUBLISHED-TTL:PT12H",
            "BEGIN:VEVENT",
            "SEQUENCE:0",
            "END:VEVENT",
            "END:VCALENDAR",
        ):
            self.assertIn(header, out)

    def test_utc_start_and_end(self):
        out = build_calendar([self.event])
        # 15:30 at UTC-05:00 -> 20:30Z; plus 150 minutes -> 23:00Z.
        self.assertIn("DTSTART:20260102T203000Z", out)
        self.assertIn("DTEND:20260102T230000Z", out)

    def test_dtstamp_derived_from_start_not_now(self):
        out = build_calendar([self.event])
        self.assertIn("DTSTAMP:20260102T203000Z", out)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.assertNotIn(f"DTSTAMP:{today}", out)

    def test_deterministic_output(self):
        first = build_calendar([self.event, self.event], name="Sports")
        second = build_calendar([self.event, self.event], name="Sports")
        self.assertEqual(first, second)

    def test_text_values_are_escaped(self):
        out = build_calendar([self.event])
        self.assertIn(r"SUMMARY:Team A vs Team B\; playoffs\, round 1", out)
        self.assertIn(r"DESCRIPTION:Line1\nLine2\\note", out)
        self.assertIn(r"LOCATION:Arena\; Section 3", out)

    def test_location_is_optional(self):
        event = dict(self.event)
        event.pop("location")
        out = build_calendar([event])
        self.assertNotIn("LOCATION:", out)

    def test_long_values_are_folded(self):
        event = dict(self.event)
        event["summary"] = "Long " * 100
        out = build_calendar([event])
        for physical in out.split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)

    def test_output_is_utf8_safe(self):
        event = dict(self.event)
        event["summary"] = "⚽" * 100
        out = build_calendar([event])
        out.encode("utf-8").decode("utf-8")
        for physical in out.split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)

    def test_empty_calendar(self):
        out = build_calendar([])
        self.assertTrue(out.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertNotIn("BEGIN:VEVENT", out)
        self.assertTrue(out.endswith("END:VCALENDAR\r\n"))


if __name__ == "__main__":
    unittest.main()
