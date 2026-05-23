"""Trigger surface — what wakes the orchestrator up."""

from .channel import EventChannel
from .types import OrchestratorEvent, TickEvent, ManualEvent

__all__ = ["EventChannel", "OrchestratorEvent", "TickEvent", "ManualEvent"]
