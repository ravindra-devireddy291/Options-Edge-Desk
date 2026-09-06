"""UI-safe audit tail: redact secrets; keep event kind strings as-is."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

SECRET_KEY_EXACT = frozenset(
    {
        "access_token",
        "refresh_token",
        "token",
        "api_key",
        "x_api_key",
        "desk_api_key",
        "totp",
        "totp_secret",
        "pin",
        "password",
        "secret",
        "authorization",
        "client_secret",
        "raw_keys",
        "bearer",
        "dhan_access_token",
        "accessToken",
        "access_token_masked",
    }
)


def _is_secret_key(key: str) -> bool:
    k = str(key or "")
    low = k.lower()
    if low in SECRET_KEY_EXACT or k in SECRET_KEY_EXACT:
        return True
    if low.endswith("_token") or low.endswith("_secret") or low.endswith("_password"):
        return True
    if "totp" in low or low.endswith("apikey"):
        return True
    return False


def redact_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    """Deep-copy event with secret fields replaced by '[redacted]'."""
    out: Dict[str, Any] = {}
    for key, value in event.items():
        if _is_secret_key(str(key)):
            out[str(key)] = "[redacted]"
        elif isinstance(value, Mapping):
            out[str(key)] = redact_event(value)
        elif isinstance(value, list):
            out[str(key)] = [
                redact_event(v) if isinstance(v, Mapping) else v for v in value
            ]
        else:
            out[str(key)] = value
    return out


def redact_events(events: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [redact_event(e) for e in events]


def clamp_limit(limit: int | None, *, default: int = 100, max_n: int = 500) -> int:
    try:
        n = int(limit if limit is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, max_n))


def public_tail(
    *,
    memory_events: Sequence[Mapping[str, Any]],
    durable_events: Sequence[Mapping[str, Any]],
    limit: int | None = 100,
) -> Dict[str, Any]:
    """Prefer durable day file; fall back to in-memory runner audit."""
    n = clamp_limit(limit)
    raw: Sequence[Mapping[str, Any]] = durable_events if durable_events else memory_events
    events = redact_events(list(raw)[-n:])
    return {"count": len(events), "events": events, "limit": n}
