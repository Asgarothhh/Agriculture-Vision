"""Простая in-memory очередь задач"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from model.schemas import JobStatusResponse, SegmentResponse


@dataclass
class _JobRecord:
    job_id: str
    status: str = "queued"
    position: int = 0
    result: SegmentResponse | None = None
    error: str | None = None


class JobQueue:
    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, _JobRecord] = {}
        self._order: deque[str] = deque()
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], SegmentResponse]) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            rec = _JobRecord(job_id=job_id, position=len(self._order))
            self._jobs[job_id] = rec
            self._order.append(job_id)

        def _run() -> None:
            with self._lock:
                self._jobs[job_id].status = "running"
                self._jobs[job_id].position = 0
            try:
                result = fn()
                with self._lock:
                    self._jobs[job_id].status = "done"
                    self._jobs[job_id].result = result
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id].status = "failed"
                    self._jobs[job_id].error = str(exc)
            finally:
                with self._lock:
                    if self._order and self._order[0] == job_id:
                        self._order.popleft()
                    self._reindex_positions()

        self._executor.submit(_run)
        return job_id

    def _reindex_positions(self) -> None:
        for i, jid in enumerate(self._order):
            if jid in self._jobs:
                self._jobs[jid].position = i

    def get(self, job_id: str) -> JobStatusResponse | None:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return None
            return JobStatusResponse(
                job_id=rec.job_id,
                status=rec.status,
                position=rec.position if rec.status == "queued" else None,
                result=rec.result,
                error=rec.error,
            )
