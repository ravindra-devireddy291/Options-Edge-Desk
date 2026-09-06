"""Execution armor types — shared NIFTY + BANKNIFTY."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SessionState(str, Enum):
    IDLE = "IDLE"
    ENTRY_WORKING = "ENTRY_WORKING"
    ENTRY_PARTIAL = "ENTRY_PARTIAL"
    ENTRY_FILLED = "ENTRY_FILLED"
    PROTECT_WORKING = "PROTECT_WORKING"
    IN_POSITION = "IN_POSITION"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"
    ERROR = "ERROR"


class DhanOrderStatus(str, Enum):
    TRANSIT = "TRANSIT"
    PENDING = "PENDING"
    PART_TRADED = "PART_TRADED"
    TRADED = "TRADED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    @classmethod
    def from_raw(cls, raw: str) -> Optional["DhanOrderStatus"]:
        if not raw:
            return None
        key = str(raw).strip().upper().replace(" ", "_")
        for m in cls:
            if m.value == key or m.name == key:
                return m
        return None


class OrderLegRole(str, Enum):
    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    EXIT = "exit"


@dataclass
class DepthSnapshot:
    security_id: str
    symbol: str
    bid: float
    ask: float
    ltp: float
    ts: datetime

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return 999.0
        return max(0.0, (self.ask - self.bid) / self.mid)


@dataclass
class ManagedSession:
    """One live entry + protective SL tracked by the armor runner."""

    client_order_id: str
    correlation_id: str
    underlying: str
    sleeve: str
    security_id: str
    symbol: str
    requested_qty: int
    stop_pct: float
    tp_pct: float
    trail_pct: float = 0.0
    trail_activate_pct: float = 0.0
    peak_px: float = 0.0
    current_stop_px: float = 0.0
    entry_order_id: str = ""
    sl_order_id: str = ""
    tp_order_id: str = ""
    filled_qty: int = 0
    pending_entry_qty: int = 0
    avg_entry_px: float = 0.0
    state: SessionState = SessionState.ENTRY_WORKING
    limit_px: float = 0.0
    exit_reason: str = ""
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DhanOrderUpdate:
    order_id: str
    status: DhanOrderStatus
    qty: int
    traded_qty: int
    remaining_qty: int
    avg_traded_price: float
    price: float
    trigger_price: float
    correlation_id: str = ""
    txn_type: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ws(cls, data: Dict[str, Any]) -> "DhanOrderUpdate":
        status = DhanOrderStatus.from_raw(str(data.get("Status") or "")) or DhanOrderStatus.PENDING
        return cls(
            order_id=str(data.get("OrderNo") or data.get("orderId") or ""),
            status=status,
            qty=int(data.get("Quantity") or 0),
            traded_qty=int(data.get("TradedQty") or 0),
            remaining_qty=int(data.get("RemainingQuantity") or 0),
            avg_traded_price=float(data.get("AvgTradedPrice") or data.get("TradedPrice") or 0),
            price=float(data.get("Price") or 0),
            trigger_price=float(data.get("TriggerPrice") or 0),
            correlation_id=str(data.get("CorrelationId") or ""),
            txn_type=str(data.get("TxnType") or ""),
            raw=dict(data),
        )

    @classmethod
    def from_rest(cls, data: Dict[str, Any]) -> "DhanOrderUpdate":
        status = DhanOrderStatus.from_raw(str(data.get("orderStatus") or "")) or DhanOrderStatus.PENDING
        traded = int(data.get("tradedQuantity") or data.get("filledQty") or data.get("TradedQty") or 0)
        qty = int(data.get("quantity") or data.get("Quantity") or 0)
        remaining = int(data.get("remainingQuantity") or data.get("RemainingQuantity") or max(0, qty - traded))
        return cls(
            order_id=str(data.get("orderId") or data.get("OrderNo") or ""),
            status=status,
            qty=qty,
            traded_qty=traded,
            remaining_qty=remaining,
            avg_traded_price=float(
                data.get("averageTradedPrice")
                or data.get("AvgTradedPrice")
                or data.get("price")
                or 0
            ),
            price=float(data.get("price") or data.get("Price") or 0),
            trigger_price=float(data.get("triggerPrice") or data.get("TriggerPrice") or 0),
            correlation_id=str(data.get("correlationId") or data.get("CorrelationId") or ""),
            txn_type=str(data.get("transactionType") or data.get("TxnType") or ""),
            raw=dict(data),
        )
