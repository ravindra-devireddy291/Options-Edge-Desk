"""Execution armor config — env-driven, book-agnostic."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ArmorConfig:
    enabled: bool = True
    max_spread_pct: float = 0.03
    max_tick_age_ms_ws: int = 500
    max_tick_age_ms_rest: int = 5000
    chase_max_slippage_pct: float = 0.015
    chase_timeout_s: float = 90.0
    chase_interval_ms: int = 800
    initial_offset_ticks: int = 1
    tick_size: float = 0.05
    default_stop_pct: float = 0.30
    default_tp_pct: float = 0.50
    use_limit_entry: bool = True
    use_limit_exit: bool = True
    attach_exchange_sl: bool = True
    attach_exchange_tp: bool = True
    reconcile_interval_s: float = 15.0
    mock_spread_gate: bool = True

    @classmethod
    def from_env(cls) -> "ArmorConfig":
        return cls(
            enabled=_flag("DESK_EXECUTION_ARMOR", True),
            max_spread_pct=float(os.environ.get("DESK_MAX_SPREAD_PCT") or 0.03),
            max_tick_age_ms_ws=int(os.environ.get("DESK_MAX_TICK_AGE_MS") or 500),
            max_tick_age_ms_rest=int(os.environ.get("DESK_MAX_TICK_AGE_MS_REST") or 5000),
            chase_max_slippage_pct=float(os.environ.get("DESK_CHASE_MAX_SLIPPAGE_PCT") or 0.015),
            chase_timeout_s=float(os.environ.get("DESK_CHASE_TIMEOUT_S") or 90.0),
            chase_interval_ms=int(os.environ.get("DESK_CHASE_INTERVAL_MS") or 800),
            initial_offset_ticks=int(os.environ.get("DESK_CHASE_OFFSET_TICKS") or 1),
            tick_size=float(os.environ.get("DESK_TICK_SIZE") or 0.05),
            default_stop_pct=float(os.environ.get("DESK_DEFAULT_STOP_PCT") or 0.30),
            default_tp_pct=float(os.environ.get("DESK_DEFAULT_TP_PCT") or 0.50),
            use_limit_entry=_flag("DESK_USE_LIMIT_ENTRY", True),
            use_limit_exit=_flag("DESK_USE_LIMIT_EXIT", True),
            attach_exchange_sl=_flag("DESK_ATTACH_EXCHANGE_SL", True),
            attach_exchange_tp=_flag("DESK_ATTACH_EXCHANGE_TP", True),
            reconcile_interval_s=float(os.environ.get("DESK_RECONCILE_INTERVAL_S") or 15.0),
            mock_spread_gate=_flag("DESK_MOCK_SPREAD_GATE", True),
        )


ARMOR = ArmorConfig.from_env()
