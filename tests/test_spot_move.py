"""Prev-day close based index change (Groww-style)."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from app.brokers.dhan.client import _spot_move
from app.session import IST


class TestSpotMove(unittest.TestCase):
    def test_vs_previous_day_close(self):
        # Yesterday last = 24219.05 → today 24334.55 = +115.50 (0.48%)
        yday = date(2026, 8, 22)
        today = date(2026, 8, 25)
        stamps = []
        closes = []
        for i in range(3):
            dt = datetime(yday.year, yday.month, yday.day, 9, 15 + i, tzinfo=IST)
            stamps.append(int(dt.astimezone(timezone.utc).timestamp()))
            closes.append(24200.0 + i)
        stamps.append(int(datetime(yday.year, yday.month, yday.day, 15, 29, tzinfo=IST).astimezone(timezone.utc).timestamp()))
        closes.append(24219.05)
        stamps.append(int(datetime(today.year, today.month, today.day, 15, 29, tzinfo=IST).astimezone(timezone.utc).timestamp()))
        closes.append(24334.55)
        move = _spot_move(closes, stamps)
        self.assertAlmostEqual(move["ltp"], 24334.55, places=2)
        self.assertAlmostEqual(move["change_pts"], 115.5, places=2)
        self.assertAlmostEqual(move["change_pct"], 0.4773, places=3)

    def test_negative_day(self):
        yday = date(2026, 8, 22)
        today = date(2026, 8, 25)
        stamps = [
            int(datetime(yday.year, yday.month, yday.day, 15, 29, tzinfo=IST).astimezone(timezone.utc).timestamp()),
            int(datetime(today.year, today.month, today.day, 15, 29, tzinfo=IST).astimezone(timezone.utc).timestamp()),
        ]
        closes = [57525.95, 57514.20]
        move = _spot_move(closes, stamps)
        self.assertAlmostEqual(move["change_pts"], -11.75, places=2)
        self.assertLess(move["change_pct"], 0)


if __name__ == "__main__":
    unittest.main()
