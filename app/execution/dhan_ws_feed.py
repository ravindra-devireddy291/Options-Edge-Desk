"""Dhan v2 market feed WebSocket — FULL packet parser + depth cache."""
from __future__ import annotations

import asyncio
import json
import struct
import urllib.parse
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from app.brokers.dhan import client as dhan
from app.execution.types import DepthSnapshot

FEED_WS = "wss://api-feed.dhan.co"
REQUEST_FULL = 21

_DEPTH: Dict[str, DepthSnapshot] = {}
_lock = asyncio.Lock()

DepthHandler = Callable[[DepthSnapshot], None]


def get_depth(security_id: str) -> Optional[DepthSnapshot]:
    return _DEPTH.get(str(security_id))


def _feed_url() -> str:
    client_id, token = dhan.credentials()
    qs = urllib.parse.urlencode(
        {"version": "2", "token": token, "clientId": client_id, "authType": "2"}
    )
    return f"{FEED_WS}?{qs}"


def parse_full_packet(data: bytes) -> Optional[DepthSnapshot]:
    if len(data) < 162 or data[0] != 8:
        return None
    sec_id = str(struct.unpack_from("<I", data, 5)[0])
    ltp = struct.unpack_from("<f", data, 8)[0]
    ltt = struct.unpack_from("<i", data, 14)[0]
    depth_raw = data[62:162]
    bid_px = ask_px = 0.0
    for i in range(5):
        off = i * 20
        bid_qty, ask_qty, _, _, bp, ap = struct.unpack_from("<iiHHff", depth_raw, off)
        if bid_qty > 0 and bp > 0 and bid_px <= 0:
            bid_px = float(bp)
        if ask_qty > 0 and ap > 0 and ask_px <= 0:
            ask_px = float(ap)
    if bid_px <= 0:
        bid_px = float(ltp)
    if ask_px <= 0:
        ask_px = float(ltp)
    ts = datetime.fromtimestamp(int(ltt), tz=timezone.utc) if ltt > 0 else datetime.now(timezone.utc)
    return DepthSnapshot(
        security_id=sec_id,
        symbol="",
        bid=bid_px,
        ask=ask_px,
        ltp=float(ltp),
        ts=ts,
    )


def parse_ltp_packet(data: bytes) -> Optional[DepthSnapshot]:
    """Ticker (2) / Quote (4) — LTP only. Used for index spots."""
    if len(data) < 16 or data[0] not in (2, 4):
        return None
    sec_id = str(struct.unpack_from("<I", data, 4)[0])
    ltp = struct.unpack_from("<f", data, 8)[0]
    ltt = struct.unpack_from("<i", data, 12)[0] if len(data) >= 16 else 0
    ts = datetime.fromtimestamp(int(ltt), tz=timezone.utc) if ltt > 0 else datetime.now(timezone.utc)
    px = float(ltp)
    return DepthSnapshot(security_id=sec_id, symbol="", bid=px, ask=px, ltp=px, ts=ts)


def parse_feed_message(data: bytes) -> Optional[DepthSnapshot]:
    if not data:
        return None
    if data[0] == 8:
        return parse_full_packet(data)
    return parse_ltp_packet(data)


def _subscribe_msg(instruments: List[Tuple[str, str]]) -> str:
    """instruments: [(exchange_segment, security_id), ...]"""
    lst = [{"ExchangeSegment": seg, "SecurityId": str(sid)} for seg, sid in instruments]
    return json.dumps({"RequestCode": REQUEST_FULL, "InstrumentCount": len(lst), "InstrumentList": lst})


async def _store(depth: DepthSnapshot) -> None:
    async with _lock:
        _DEPTH[str(depth.security_id)] = depth


async def run_feed(
    instruments: List[Tuple[str, str]],
    *,
    on_depth: Optional[DepthHandler] = None,
    stop: Optional[asyncio.Event] = None,
) -> None:
    """Connect to Dhan market feed; update depth cache for subscribed ids."""
    import websockets

    if not instruments:
        return
    url = _feed_url()
    while stop is None or not stop.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=40) as ws:
                for i in range(0, len(instruments), 100):
                    chunk = instruments[i : i + 100]
                    await ws.send(_subscribe_msg(chunk))
                async for msg in ws:
                    if stop and stop.is_set():
                        break
                    if not isinstance(msg, bytes):
                        continue
                    depth = parse_feed_message(msg)
                    if depth:
                        await _store(depth)
                        if on_depth:
                            on_depth(depth)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(2.0)
