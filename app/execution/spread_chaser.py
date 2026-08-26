"""Spread-aware limit price for entry and exit."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from app.execution.config import ArmorConfig
from app.execution.types import DepthSnapshot


@dataclass
class ChaseQuote:
    limit_px: float
    spread_pct: float
    refused: bool
    reason: str = ""


def next_limit_price(
    depth: DepthSnapshot,
    cfg: ArmorConfig,
    *,
    ref_px: Optional[float] = None,
    side: Literal["buy", "sell"] = "buy",
) -> ChaseQuote:
    bid = float(depth.bid)
    ask = float(depth.ask)
    if bid <= 0 or ask <= 0 or ask < bid:
        return ChaseQuote(0.0, 999.0, True, "invalid_depth")

    spread_pct = depth.spread_pct
    if spread_pct > cfg.max_spread_pct:
        return ChaseQuote(0.0, spread_pct, True, f"spread_{spread_pct:.4f}_gt_max")

    tick = float(cfg.tick_size)
    offset = max(0, int(cfg.initial_offset_ticks)) * tick
    anchor = ref_px if ref_px and ref_px > 0 else depth.mid

    if side == "buy":
        limit_px = bid + offset
        limit_px = min(limit_px, ask - tick)
        cap = anchor * (1.0 + float(cfg.chase_max_slippage_pct))
        limit_px = min(limit_px, cap)
    else:
        limit_px = ask - offset
        limit_px = max(limit_px, bid + tick)
        floor = anchor * (1.0 - float(cfg.chase_max_slippage_pct))
        limit_px = max(limit_px, floor)

    limit_px = max(tick, round(limit_px / tick) * tick)
    return ChaseQuote(limit_px, spread_pct, False)
