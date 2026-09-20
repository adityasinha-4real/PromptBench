"""In-memory tracking of in-flight benchmark runs.

Holds live per-target state, the cancellation signal, and the fan-out queues
that feed the SSE progress stream. Completed runs are the database's job; this
only covers the window while a run is executing (plus a short grace period so a
client that connects late still sees the terminal event).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.models.benchmark import ResultStatus, RunStatus

logger = get_logger(__name__)

#: How long a finished run stays queryable in memory after completion.
RETENTION_SECONDS = 300.0
#: Bounded so a stalled SSE client cannot grow memory without limit.
SUBSCRIBER_QUEUE_SIZE = 64


@dataclass
class TaskState:
    """Live state of one (model x variant) execution."""

    key: str
    provider: str
    model: str
    variant_name: str
    status: str = ResultStatus.QUEUED
    latency_ms: int | None = None
    attempts: int = 0
    error_code: str | None = None
    error_message: str | None = None
    result_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "provider": self.provider,
            "model": self.model,
            "variant_name": self.variant_name,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "result_id": self.result_id,
        }


@dataclass
class RunState:
    """Everything the progress stream needs about one run."""

    run_id: int
    benchmark_id: int
    tasks: dict[str, TaskState] = field(default_factory=dict)
    status: str = RunStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    finished_at_monotonic: float | None = None

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def snapshot(self) -> dict[str, Any]:
        tasks = list(self.tasks.values())
        terminal = {ResultStatus.SUCCESS, ResultStatus.FAILED, ResultStatus.CANCELLED}
        return {
            "run_id": self.run_id,
            "benchmark_id": self.benchmark_id,
            "status": self.status,
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t.status in terminal),
            "succeeded": sum(1 for t in tasks if t.status == ResultStatus.SUCCESS),
            "failed": sum(1 for t in tasks if t.status == ResultStatus.FAILED),
            "tasks": [t.to_dict() for t in tasks],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class RunTracker:
    """Process-wide registry of active runs."""

    def __init__(self) -> None:
        self._runs: dict[int, RunState] = {}
        self._lock = asyncio.Lock()

    async def create(self, run_id: int, benchmark_id: int, tasks: list[TaskState]) -> RunState:
        async with self._lock:
            self._evict_expired()
            state = RunState(
                run_id=run_id,
                benchmark_id=benchmark_id,
                tasks={t.key: t for t in tasks},
            )
            self._runs[run_id] = state
            return state

    def get(self, run_id: int) -> RunState | None:
        return self._runs.get(run_id)

    def active_run_ids(self) -> list[int]:
        return [rid for rid, s in self._runs.items() if s.status == RunStatus.RUNNING]

    def publish(self, state: RunState) -> None:
        """Broadcast the current snapshot to every subscriber (never blocks)."""
        if not state.subscribers:
            return
        snapshot = state.snapshot()
        for queue in list(state.subscribers):
            try:
                queue.put_nowait(snapshot)
            except asyncio.QueueFull:
                # Drop the oldest frame; the newest snapshot is always sufficient.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(snapshot)

    def subscribe(self, state: RunState) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        state.subscribers.add(queue)
        queue.put_nowait(state.snapshot())
        return queue

    def unsubscribe(self, state: RunState, queue: asyncio.Queue[dict[str, Any]]) -> None:
        state.subscribers.discard(queue)

    def cancel(self, run_id: int) -> bool:
        """Signal cancellation. Returns False when the run is unknown or finished."""
        state = self._runs.get(run_id)
        if state is None or state.status != RunStatus.RUNNING:
            return False
        state.cancel_event.set()
        logger.info("Cancellation requested for run %s", run_id)
        return True

    def finish(self, state: RunState) -> None:
        state.finished_at_monotonic = time.monotonic()
        self.publish(state)
        # Wake any stream still waiting so it can close cleanly.
        for queue in list(state.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait({"_terminal": True, **state.snapshot()})

    def _evict_expired(self) -> None:
        now = time.monotonic()
        stale = [
            rid
            for rid, s in self._runs.items()
            if s.finished_at_monotonic is not None
            and now - s.finished_at_monotonic > RETENTION_SECONDS
            and not s.subscribers
        ]
        for rid in stale:
            self._runs.pop(rid, None)


_tracker: RunTracker | None = None


def get_tracker() -> RunTracker:
    global _tracker
    if _tracker is None:
        _tracker = RunTracker()
    return _tracker


def reset_tracker() -> None:
    """Used by tests to isolate state between cases."""
    global _tracker
    _tracker = None
