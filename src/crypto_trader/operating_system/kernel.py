"""AI Fund Operating System kernel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProcessState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"


@dataclass
class OSProcess:
    name: str
    state: ProcessState = ProcessState.STOPPED
    restart_count: int = 0
    last_error: str | None = None


class OSKernel:
    def __init__(self) -> None:
        self.processes: dict[str, OSProcess] = {}

    def register(self, name: str) -> OSProcess:
        process = OSProcess(name=name)
        self.processes[name] = process
        return process

    def start(self, name: str) -> OSProcess:
        process = self.processes.setdefault(name, OSProcess(name=name))
        process.state = ProcessState.RUNNING
        return process

    def stop(self, name: str) -> OSProcess:
        process = self.processes.setdefault(name, OSProcess(name=name))
        process.state = ProcessState.STOPPED
        return process

    def degrade(self, name: str, error: str) -> OSProcess:
        process = self.processes.setdefault(name, OSProcess(name=name))
        process.state = ProcessState.DEGRADED
        process.last_error = error
        return process

    def restart(self, name: str) -> OSProcess:
        process = self.processes.setdefault(name, OSProcess(name=name))
        process.restart_count += 1
        process.state = ProcessState.RUNNING
        process.last_error = None
        return process

    def healthy(self) -> bool:
        return all(
            p.state in (ProcessState.RUNNING, ProcessState.STARTING)
            for p in self.processes.values()
        )
