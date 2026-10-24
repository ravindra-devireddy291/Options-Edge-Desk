"""Groww session and orders. Local mode never calls the network."""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Protocol


IST = timezone(timedelta(hours=5, minutes=30))


class GrowwGateway(Protocol):
    def session(self, token: str, secret: str) -> tuple[str, str, str]: ...

    def funds(self, access: str, fallback: float) -> float: ...

    def place(self, access: str, side: str, contract: str, lots: int) -> str: ...


def _expiry_iso() -> str:
    now = datetime.now(IST)
    nxt = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now >= nxt:
        nxt = nxt + timedelta(days=1)
    return nxt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LocalGroww:
    """Records the order locally. Funds come from the client row."""

    def session(self, token: str, secret: str) -> tuple[str, str, str]:
        if len(token.strip()) < 20 or len(secret.strip()) < 8:
            raise ValueError("bad groww key")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return "local-" + digest, "LOCAL", _expiry_iso()

    def funds(self, access: str, fallback: float) -> float:
        return float(fallback)

    def place(self, access: str, side: str, contract: str, lots: int) -> str:
        stamp = hashlib.sha256(f"{access}:{side}:{contract}:{lots}".encode()).hexdigest()[:12]
        return "local-" + stamp


class LiveGroww:
    """TOTP access token. Used only when GROWW_MODE=live on the desk machine."""

    def session(self, token: str, secret: str) -> tuple[str, str, str]:
        from app.brokers.groww.totp import totp_now

        body = json.dumps({"totp": totp_now(secret)}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groww.in/v1/token/api/access",
            data=body,
            headers={"Authorization": "Bearer " + token.strip(), "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            payload = json.loads(res.read().decode("utf-8"))
        access = str(payload.get("token") or payload.get("access_token") or payload.get("accessToken") or "")
        if not access:
            raise ValueError("groww token missing")
        client_id = str(payload.get("client_id") or payload.get("groww_client_id") or "")
        return access, client_id, _expiry_iso()

    def funds(self, access: str, fallback: float) -> float:
        req = urllib.request.Request(
            "https://api.groww.in/v1/margins/detail/user",
            headers={"Authorization": "Bearer " + access, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            payload = json.loads(res.read().decode("utf-8"))
        for key in ("clear_cash", "available_margin", "net_margin", "funds"):
            if payload.get(key) is not None:
                return float(payload[key])
        cash = payload.get("payload") or payload.get("data") or {}
        if isinstance(cash, dict):
            for key in ("clear_cash", "available_margin", "net_margin"):
                if cash.get(key) is not None:
                    return float(cash[key])
        raise ValueError("groww funds missing")

    def place(self, access: str, side: str, contract: str, lots: int) -> str:
        raise ValueError("live place needs the contract map from the desk signal")


def gateway() -> GrowwGateway:
    mode = (os.environ.get("GROWW_MODE") or "local").strip().lower()
    if mode == "live":
        if os.environ.get("CLIENT_EXECUTION_APPROVED") != "1":
            raise RuntimeError(
                "Live client execution is disabled. Set CLIENT_EXECUTION_APPROVED=1 only after legal and risk sign-off"
            )
        return LiveGroww()
    return LocalGroww()
