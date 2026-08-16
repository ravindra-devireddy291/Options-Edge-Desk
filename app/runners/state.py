"""In-process desk runner state (paper/live trading control plane).

Important: Start/Stop toggles TRADING only. The FastAPI/uvicorn process on the VPS
stays up so health, positions, signals, and token auto-renew keep working.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _state_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "trading_state.json"


@dataclass
class KillSwitch:
    active: bool = False
    activated_at: Optional[str] = None
    operator_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class RunnerState:
    # RUNNING = trading armed; STOPPED = no new cycles/orders (desk API still alive)
    state: str = "STOPPED"
    mode: str = "paper"
    task_id: Optional[str] = None
    started_at: Optional[str] = None
    last_error: Optional[str] = None
    stop_requested: bool = False
    cycles_completed: int = 0
    last_cycle_at: Optional[str] = None
    last_sync_at: Optional[str] = None
    signals_collected: int = 0
    signals_approved: int = 0
    signals_rejected: int = 0
    orders_executed: int = 0
    exits_executed: int = 0
    execution: str = "manual"  # manual | auto (all modes)
    replay_day: Optional[str] = None
    speed: float = 60.0
    paper_auto_schedule: bool = False
    paused_day: Optional[str] = None
    seq: int = 0
    kill: KillSwitch = field(default_factory=KillSwitch)
    order_queue: List[Dict[str, Any]] = field(default_factory=list)
    audit: List[Dict[str, Any]] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def trading_active(self) -> bool:
        return self.state.upper() == "RUNNING" and not self.kill.active and not self.stop_requested

    def bump_seq(self) -> int:
        """Monotonic desk sequence for snapshot / WS gap detection."""
        with self._lock:
            self.seq += 1
            return self.seq

    def bump_cycle(self) -> None:
        with self._lock:
            self.cycles_completed += 1
            self.last_cycle_at = _now()

    def audit_event(self, kind: str, **payload: Any) -> None:
        with self._lock:
            self.audit.append({"ts": _now(), "kind": kind, **payload})
            if len(self.audit) > 2000:
                self.audit = self.audit[-1500:]
        try:
            from app.desk_log import append_event

            append_event(kind, **payload)
        except Exception:
            pass

    def enqueue(self, order: Dict[str, Any]) -> None:
        with self._lock:
            self.order_queue.append(order)

    def persist(self) -> None:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {
                "state": self.state,
                "mode": self.mode,
                "task_id": self.task_id,
                "started_at": self.started_at,
                "stop_requested": self.stop_requested,
                "kill_active": self.kill.active,
                "kill_reason": self.kill.reason,
                "last_sync_at": self.last_sync_at,
                "execution": self.execution,
                "replay_day": self.replay_day,
                "speed": self.speed,
                "paper_auto_schedule": self.paper_auto_schedule,
                "paused_day": self.paused_day,
                "updated_at": _now(),
            }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> None:
        path = _state_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        with self._lock:
            # Never auto-resume live trading after process restart — stay STOPPED
            # unless explicitly RUNNING was saved in paper and operator wants it.
            # Safer default: always boot STOPPED; remember mode only.
            self.mode = str(raw.get("mode") or self.mode)
            self.state = "STOPPED"
            self.stop_requested = False
            self.started_at = None
            self.task_id = None
            if raw.get("kill_active"):
                self.kill.active = True
                self.kill.reason = raw.get("kill_reason")
                self.kill.activated_at = _now()
            self.last_sync_at = raw.get("last_sync_at")
            self.execution = str(raw.get("execution") or "manual")
            self.replay_day = raw.get("replay_day")
            self.paper_auto_schedule = bool(raw.get("paper_auto_schedule"))
            self.paused_day = raw.get("paused_day")
            try:
                from app.desk_log import load_today

                self.audit = load_today(400)
            except Exception:
                pass
            try:
                self.speed = float(raw.get("speed") or 60.0)
            except (TypeError, ValueError):
                self.speed = 60.0

    def status(self) -> Dict[str, Any]:
        with self._lock:
            rate = (
                self.signals_approved / self.signals_collected
                if self.signals_collected
                else 0.0
            )
            return {
                "state": self.state,
                "mode": self.mode,
                "task_id": self.task_id,
                "started_at": self.started_at,
                "last_error": self.last_error,
                "stop_requested": self.stop_requested,
                "trading_active": self.state.upper() == "RUNNING"
                and not self.kill.active
                and not self.stop_requested,
                "desk_process": "alive",
                "control_plane": "trading_only",
                "statistics": {
                    "cycles_completed": self.cycles_completed,
                    "total_signals_collected": self.signals_collected,
                    "total_signals_approved": self.signals_approved,
                    "total_signals_rejected": self.signals_rejected,
                    "total_orders_executed": self.orders_executed,
                    "total_exits_executed": self.exits_executed,
                    "approval_rate": round(rate, 4),
                    "mode": self.mode,
                    "last_cycle_at": self.last_cycle_at,
                },
            }


RUNNER = RunnerState()
RUNNER.load()
