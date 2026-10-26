"""Background worker: one thread running periodic tasks (send scheduled mail, wake
snoozed conversations, sync mailboxes, deliver webhooks, shift reminders...).

Modules contribute tasks through a ``worker_tasks()`` function returning
``[Task(...), ...]``; see modules.py. Each task runs in its own try/except so one
failing integration never stalls the others.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from pps_tools.switchboard import db

logger = logging.getLogger(__name__)


@dataclass
class Task:
    name: str
    interval: float                      # seconds between runs
    fn: Callable[[], object]
    next_run: float = field(default=0.0)
    last_error: str | None = None
    last_run: float | None = None


class Worker(threading.Thread):
    def __init__(self, tasks: list[Task], tick: float = 1.0):
        super().__init__(name="switchboard-worker", daemon=True)
        self.tasks = tasks
        self.tick = tick
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # pragma: no cover - exercised manually; tasks are unit tested
        logger.info("Worker started with %d tasks", len(self.tasks))
        try:
            while not self._stop.is_set():
                self.run_due()
                self._stop.wait(self.tick)
        finally:
            db.close()

    def run_due(self) -> None:
        now = time.monotonic()
        for task in self.tasks:
            if now < task.next_run:
                continue
            task.next_run = now + task.interval
            run_task(task)


def run_task(task: Task) -> None:
    try:
        task.fn()
        task.last_error = None
    except Exception as exc:  # keep going; report on the next run
        task.last_error = str(exc)
        logger.exception("Worker task %s failed", task.name)
    finally:
        task.last_run = time.time()
