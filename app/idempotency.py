"""Place idempotency: same trace_id returns the original result.

UI traces: 30s. Auto-engine traces (`auto:…`): 8h to block double-fills on live capital.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

TTL_SEC = 30.0
AUTO_TTL_SEC = 8 * 3600.0
_lock = threading.RLock()
_store: Dict[str, Tuple[float, Any, float]] = {}


def get(trace_id: Optional[str]) -> Optional[Any]:
    tid = (trace_id or "").strip()
    if not tid:
        return None
    now = time.monotonic()
    with _lock:
        hit = _store.get(tid)
        if not hit:
            return None
        ts, payload, ttl = hit
        if now - ts > ttl:
            _store.pop(tid, None)
            return None
        return payload


def put(trace_id: Optional[str], payload: Any, ttl_sec: Optional[float] = None) -> None:
    tid = (trace_id or "").strip()
    if not tid:
        return
    ttl = float(ttl_sec if ttl_sec is not None else (AUTO_TTL_SEC if tid.startswith("auto:") else TTL_SEC))
    now = time.monotonic()
    with _lock:
        _store[tid] = (now, payload, ttl)
        if len(_store) > 200:
            dead = [k for k, (ts, _, t) in _store.items() if now - ts > t]
            for k in dead:
                _store.pop(k, None)
