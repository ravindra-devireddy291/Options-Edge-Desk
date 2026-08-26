"""Multiplexed /ws/desk fan-out for snapshot deltas."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

from app.runners.state import RUNNER

CHANNELS = [
    "health.tick",
    "signal.trigger",
    "signal.clear",
    "account.patch",
    "mark.batch",
    "position.upsert",
    "position.remove",
    "order.upsert",
    "order.remove",
    "trade.append",
]

# Book mutations bump seq so UI can detect gaps.
_BOOK_EVENTS = frozenset(
    {
        "position.upsert",
        "position.remove",
        "order.upsert",
        "order.remove",
        "trade.append",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class WsHub:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register(self, websocket: WebSocket) -> None:
        self._clients.add(websocket)

    def unregister(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    def has_clients(self) -> bool:
        return bool(self._clients)

    def broadcast(self, event_type: str, data: Any, *, bump: Optional[bool] = None) -> Optional[int]:
        """Queue a WS frame to all clients. Safe from sync OMS / mock threads."""
        do_bump = bump if bump is not None else event_type in _BOOK_EVENTS
        seq = RUNNER.bump_seq() if do_bump else RUNNER.seq
        frame = {
            "type": event_type,
            "server_time": _now(),
            "data": data if data is not None else {},
            "seq": seq,
        }
        loop = self._loop
        if loop is None or not loop.is_running():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return seq
        asyncio.run_coroutine_threadsafe(self._fanout(frame), loop)
        return seq

    async def _fanout(self, frame: Dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


HUB = WsHub()
