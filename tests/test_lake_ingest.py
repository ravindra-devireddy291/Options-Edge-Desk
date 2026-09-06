"""EOD lake window + download range clamps. Does not call Dhan."""
from __future__ import annotations

import unittest
from datetime import date, datetime

from app.lake_ingest import clamp_export_range, ingest_days, latest_ingest_day
from app.session import IST


def _ist(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


class TestLakeIngestWindow(unittest.TestCase):
    def test_friday_after_close_waits_until_1535(self) -> None:
        self.assertEqual(latest_ingest_day(_ist(2026, 8, 28, 15, 32)), date(2026, 8, 27))
        self.assertEqual(latest_ingest_day(_ist(2026, 8, 28, 15, 40)), date(2026, 8, 28))

    def test_monday_morning_catches_friday(self) -> None:
        self.assertEqual(latest_ingest_day(_ist(2026, 8, 31, 10, 0)), date(2026, 8, 28))

    def test_saturday_stays_on_friday(self) -> None:
        self.assertEqual(latest_ingest_day(_ist(2026, 8, 29, 12, 0)), date(2026, 8, 28))

    def test_catchup_weekdays_only(self) -> None:
        days = ingest_days(date(2026, 8, 27), date(2026, 8, 31))
        self.assertEqual(days, [date(2026, 8, 28), date(2026, 8, 31)])

    def test_first_run_is_latest_day_only(self) -> None:
        self.assertEqual(ingest_days(None, date(2026, 8, 28)), [date(2026, 8, 28)])

    def test_up_to_date_is_empty(self) -> None:
        self.assertEqual(ingest_days(date(2026, 8, 28), date(2026, 8, 28)), [])

    def test_export_rejects_future_and_oversize(self) -> None:
        latest = date(2026, 8, 28)
        self.assertIsNone(clamp_export_range("2026-08-20", "2026-08-28", "options", latest))
        self.assertIsNotNone(clamp_export_range("2026-08-22", "2026-08-28", "options", latest))
        self.assertIsNone(clamp_export_range("2026-08-28", "2026-08-29", "spot", latest))
        self.assertIsNotNone(clamp_export_range("2026-08-01", "2026-08-28", "spot", latest))


if __name__ == "__main__":
    unittest.main()
