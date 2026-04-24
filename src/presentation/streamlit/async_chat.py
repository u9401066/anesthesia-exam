"""Small background job store for non-blocking Streamlit chat streaming."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Literal

JobStatus = Literal["running", "done", "error", "cancelled"]


@dataclass
class ChatStreamJob:
    """Mutable state for one assistant streaming response."""

    job_id: str
    status: JobStatus = "running"
    chunks: list[str] = field(default_factory=list)
    error: str = ""
    updated_at: float = field(default_factory=time.monotonic)

    @property
    def content(self) -> str:
        return "".join(self.chunks)


class ChatStreamJobStore:
    """Thread-safe in-memory store for chat streaming jobs."""

    def __init__(self, max_jobs: int = 128) -> None:
        if max_jobs < 1:
            raise ValueError("max_jobs must be >= 1")
        self._jobs: dict[str, ChatStreamJob] = {}
        self._lock = threading.Lock()
        self._max_jobs = int(max_jobs)

    def start(self, stream_factory: Callable[[], Iterator[str]]) -> str:
        """Start consuming a stream on a daemon thread and return immediately."""
        job_id = uuid.uuid4().hex
        with self._lock:
            self._prune_terminal_jobs_locked()
            self._jobs[job_id] = ChatStreamJob(job_id=job_id)

        thread = threading.Thread(
            target=self._consume_stream,
            args=(job_id, stream_factory),
            daemon=True,
            name=f"chat-stream-{job_id[:8]}",
        )
        thread.start()
        return job_id

    def cancel(self, job_id: str, reason: str = "cancelled") -> bool:
        """Mark an in-flight job cancelled so the UI can recover immediately."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status == "cancelled":
                return True
            if job.status in {"done", "error"}:
                return False
            job.status = "cancelled"
            job.error = str(reason or "cancelled")
            job.updated_at = time.monotonic()
            return True

    def snapshot(self, job_id: str) -> dict[str, str]:
        """Return a copy of the current job state for UI rendering."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"job_id": job_id, "status": "error", "content": "", "error": "chat job not found"}
            return {
                "job_id": job.job_id,
                "status": job.status,
                "content": job.content,
                "error": job.error,
            }

    def _consume_stream(self, job_id: str, stream_factory: Callable[[], Iterator[str]]) -> None:
        try:
            for chunk in stream_factory():
                if not chunk:
                    continue
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is None or job.status == "cancelled":
                        return
                    job.chunks.append(str(chunk))
                    job.updated_at = time.monotonic()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.status == "cancelled":
                    return
                job.status = "done"
                job.updated_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.status == "cancelled":
                    return
                job.status = "error"
                job.error = str(exc)
                job.updated_at = time.monotonic()
        finally:
            with self._lock:
                self._prune_terminal_jobs_locked()

    def _prune_terminal_jobs_locked(self) -> None:
        if len(self._jobs) < self._max_jobs:
            return

        terminal_job_ids = [
            job_id for job_id, job in self._jobs.items() if job.status in {"done", "error", "cancelled"}
        ]
        terminal_job_ids.sort(key=lambda job_id: self._jobs[job_id].updated_at)

        while len(self._jobs) >= self._max_jobs and terminal_job_ids:
            stale_job_id = terminal_job_ids.pop(0)
            self._jobs.pop(stale_job_id, None)
