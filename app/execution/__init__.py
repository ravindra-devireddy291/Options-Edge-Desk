"""Execution armor — shared OMS for NIFTY + BANKNIFTY."""
from app.execution.armor import place_armed_entry
from app.execution.config import ARMOR
from app.execution.runner import EXECUTION

__all__ = ["ARMOR", "EXECUTION", "place_armed_entry"]
