"""Response envelope helpers matching my-options-trader ApiEnvelope."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ok(data: Any = None) -> Dict[str, Any]:
    return {"ok": True, "server_time": utc_now(), "data": data}


def err(detail: str, *, code: str = "error") -> Dict[str, Any]:
    return {"ok": False, "server_time": utc_now(), "code": code, "detail": detail}
