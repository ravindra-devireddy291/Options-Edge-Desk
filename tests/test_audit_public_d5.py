"""D5: audit tail redaction + public shape."""
from __future__ import annotations

import unittest

from app.audit_public import clamp_limit, public_tail, redact_event


class TestAuditPublicD5(unittest.TestCase):
    def test_redact_nested_secrets(self) -> None:
        raw = {
            "ts": "2026-08-26T10:00:00Z",
            "kind": "token.renew_manual",
            "access_token": "SECRET_TOKEN_VALUE",
            "nested": {"totp_secret": "OTPSECRET", "ok": True},
            "pin": "1234",
            "operator_id": "ops",
        }
        out = redact_event(raw)
        self.assertEqual(out["kind"], "token.renew_manual")
        self.assertEqual(out["access_token"], "[redacted]")
        self.assertEqual(out["nested"]["totp_secret"], "[redacted]")
        self.assertTrue(out["nested"]["ok"])
        self.assertEqual(out["pin"], "[redacted]")
        self.assertEqual(out["operator_id"], "ops")

    def test_public_tail_prefers_durable_and_clamps(self) -> None:
        durable = [
            {"ts": "2026-08-26T09:00:00Z", "kind": "trading.start", "mode": "paper"},
            {"ts": "2026-08-26T09:10:00Z", "kind": "order.paper_place", "access_token": "leak"},
            {"ts": "2026-08-26T09:20:00Z", "kind": "trading.stop", "reason": "eod"},
        ]
        memory = [{"ts": "x", "kind": "should_not_win", "api_key": "k"}]
        payload = public_tail(memory_events=memory, durable_events=durable, limit=2)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["count"], 2)
        kinds = [e["kind"] for e in payload["events"]]
        self.assertEqual(kinds, ["order.paper_place", "trading.stop"])
        self.assertEqual(payload["events"][0]["access_token"], "[redacted]")

    def test_fallback_memory_when_durable_empty(self) -> None:
        memory = [
            {"ts": "2026-08-26T08:00:00Z", "kind": "lab.journal", "ok": True},
            {"ts": "2026-08-26T08:01:00Z", "kind": "trading.schedule_arm", "mode": "paper"},
        ]
        payload = public_tail(memory_events=memory, durable_events=[], limit=100)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["events"][0]["kind"], "lab.journal")

    def test_clamp_limit(self) -> None:
        self.assertEqual(clamp_limit(None), 100)
        self.assertEqual(clamp_limit(0), 1)
        self.assertEqual(clamp_limit(9999), 500)


if __name__ == "__main__":
    unittest.main()
