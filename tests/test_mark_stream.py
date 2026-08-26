"""Tests for conflated mark.batch + ticker/quote feed parse."""
from __future__ import annotations

import struct
import unittest
from datetime import datetime, timezone

from app.desk_events import position_key
from app.execution.dhan_ws_feed import parse_feed_message, parse_ltp_packet
from app.mark_stream import (
    _fp,
    build_paper_batch,
    drop_position,
    note_position,
    reset,
    sync_rows,
    tracked_security_ids,
)


class TestPositionKey(unittest.TestCase):
    def test_prefers_security_id(self):
        self.assertEqual(position_key({"security_id": "44118", "underlying": "NIFTY"}), "44118")

    def test_composite_fallback(self):
        self.assertEqual(
            position_key(
                {
                    "underlying": "NIFTY",
                    "strike": 25000,
                    "option_type": "PE",
                    "expiry": "2026-08-27",
                }
            ),
            "NIFTY|25000|PE|2026-08-27",
        )


class TestMarkStream(unittest.TestCase):
    def setUp(self):
        reset()

    def test_sync_and_track_ids(self):
        sync_rows(
            [
                {
                    "security_id": "111",
                    "underlying": "NIFTY",
                    "strike": 25000,
                    "option_type": "PE",
                    "expiry": "2026-08-27",
                    "qty": 65,
                    "average_price": 100.0,
                    "ltp": 101.0,
                    "unrealized_pnl": 65.0,
                },
                {"security_id": "222", "qty": 0},
            ]
        )
        self.assertEqual(tracked_security_ids(), ["111"])

    def test_paper_batch_uses_avg_and_qty_when_no_depth(self):
        note_position(
            {
                "security_id": "111",
                "underlying": "NIFTY",
                "strike": 25000,
                "option_type": "PE",
                "expiry": "2026-08-27",
                "qty": 65,
                "average_price": 100.0,
                "ltp": 102.0,
            }
        )
        batch = build_paper_batch()
        self.assertEqual(batch["open_positions"], 1)
        self.assertEqual(len(batch["marks"]), 1)
        self.assertEqual(batch["marks"][0]["key"], "111")
        self.assertEqual(batch["marks"][0]["ltp"], 102.0)
        self.assertEqual(batch["marks"][0]["unrealized_pnl"], 130.0)
        self.assertEqual(batch["unrealized_pnl"], 130.0)

    def test_drop_position(self):
        note_position({"security_id": "111", "qty": 65, "average_price": 1, "ltp": 1, "underlying": "NIFTY"})
        drop_position("111")
        self.assertEqual(tracked_security_ids(), [])

    def test_fingerprint_stable(self):
        a = {"nifty_spot": 1, "banknifty_spot": 2, "unrealized_pnl": 3, "today_net": 4, "marks": [{"key": "k", "ltp": 1, "unrealized_pnl": 0}]}
        b = dict(a)
        self.assertEqual(_fp(a), _fp(b))


class TestLtpPacket(unittest.TestCase):
    def test_ticker(self):
        buf = bytearray(16)
        buf[0] = 2
        struct.pack_into("<I", buf, 4, 13)
        struct.pack_into("<f", buf, 8, 24812.5)
        struct.pack_into("<i", buf, 12, int(datetime.now(timezone.utc).timestamp()))
        depth = parse_ltp_packet(bytes(buf))
        self.assertIsNotNone(depth)
        assert depth is not None
        self.assertEqual(depth.security_id, "13")
        self.assertAlmostEqual(depth.ltp, 24812.5, places=1)

    def test_feed_message_routes_ticker(self):
        buf = bytearray(16)
        buf[0] = 2
        struct.pack_into("<I", buf, 4, 25)
        struct.pack_into("<f", buf, 8, 51200.0)
        depth = parse_feed_message(bytes(buf))
        self.assertIsNotNone(depth)
        assert depth is not None
        self.assertEqual(depth.security_id, "25")


if __name__ == "__main__":
    unittest.main()
