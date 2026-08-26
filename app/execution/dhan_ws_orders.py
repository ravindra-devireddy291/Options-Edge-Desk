"""Dhan live order-update WebSocket."""
from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional

from app.brokers.dhan import client as dhan
from app.execution.types import DhanOrderUpdate

ORDER_WS = "wss://api-order-update.dhan.co"

OrderHandler = Callable[[DhanOrderUpdate], None]


def _login_payload() -> dict:
    client_id, token = dhan.credentials()
    return {
        "LoginReq": {"MsgCode": 42, "ClientId": client_id, "Token": token},
        "UserType": "SELF",
    }


async def run_order_updates(
    *,
    on_order: OrderHandler,
    stop: Optional[asyncio.Event] = None,
) -> None:
    import websockets

    while stop is None or not stop.is_set():
        try:
            async with websockets.connect(ORDER_WS, ping_interval=20, ping_timeout=40) as ws:
                await ws.send(json.dumps(_login_payload()))
                async for msg in ws:
                    if stop and stop.is_set():
                        break
                    if not isinstance(msg, str):
                        continue
                    try:
                        payload = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("Type") or "").lower() != "order_alert":
                        continue
                    data = payload.get("Data") or {}
                    upd = DhanOrderUpdate.from_ws(data)
                    if upd.order_id:
                        on_order(upd)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(2.0)
