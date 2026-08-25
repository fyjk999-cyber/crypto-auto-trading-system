"""System lifecycle manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleState(str, Enum):
    BOOT = "BOOT"
    READY = "READY"
    RUNNING = "RUNNING"
    MAINTENANCE = "MAINTENANCE"
    SHUTDOWN = "SHUTDOWN"


@dataclass
class LifecycleStatus:
    state: LifecycleState = LifecycleState.BOOT
    ready_gates: dict = field(default_factory=dict)

    def gate(self, name: str, passed: bool) -> None:
        self.ready_gates[name] = passed

    def is_ready(self) -> bool:
        return bool(self.ready_gates) and all(self.ready_gates.values())
