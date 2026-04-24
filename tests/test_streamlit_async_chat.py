import time
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.presentation.streamlit.async_chat import ChatStreamJobStore


def test_chat_stream_job_collects_chunks_without_blocking_start() -> None:
    store = ChatStreamJobStore()

    def slow_stream():
        yield "hel"
        time.sleep(0.05)
        yield "lo"

    started_at = time.monotonic()
    job_id = store.start(slow_stream)
    start_elapsed = time.monotonic() - started_at

    assert start_elapsed < 0.03

    deadline = time.monotonic() + 1
    snapshot = store.snapshot(job_id)
    while snapshot["status"] != "done" and time.monotonic() < deadline:
        time.sleep(0.01)
        snapshot = store.snapshot(job_id)

    assert snapshot["status"] == "done"
    assert snapshot["content"] == "hello"
    assert snapshot["error"] == ""


def test_chat_stream_job_records_errors() -> None:
    store = ChatStreamJobStore()

    def failing_stream():
        yield "partial"
        raise RuntimeError("boom")

    job_id = store.start(failing_stream)

    deadline = time.monotonic() + 1
    snapshot = store.snapshot(job_id)
    while snapshot["status"] != "error" and time.monotonic() < deadline:
        time.sleep(0.01)
        snapshot = store.snapshot(job_id)

    assert snapshot["status"] == "error"
    assert snapshot["content"] == "partial"
    assert snapshot["error"] == "boom"


def test_chat_stream_job_records_errors_before_first_chunk() -> None:
    store = ChatStreamJobStore()

    def failing_stream():
        raise RuntimeError("explode early")

    job_id = store.start(failing_stream)

    deadline = time.monotonic() + 1
    snapshot = store.snapshot(job_id)
    while snapshot["status"] != "error" and time.monotonic() < deadline:
        time.sleep(0.01)
        snapshot = store.snapshot(job_id)

    assert snapshot["status"] == "error"
    assert snapshot["content"] == ""
    assert snapshot["error"] == "explode early"


def test_chat_stream_job_can_be_cancelled_while_source_is_waiting() -> None:
    store = ChatStreamJobStore()
    started = threading.Event()
    unblock = threading.Event()

    def waiting_stream():
        started.set()
        unblock.wait(timeout=1)
        yield "late"

    job_id = store.start(waiting_stream)
    assert started.wait(timeout=0.2)

    cancelled = store.cancel(job_id, reason="manual stop")
    assert cancelled is True

    snapshot = store.snapshot(job_id)
    assert snapshot["status"] == "cancelled"
    assert snapshot["content"] == ""
    assert snapshot["error"] == "manual stop"

    unblock.set()
    time.sleep(0.05)
    snapshot = store.snapshot(job_id)
    assert snapshot["status"] == "cancelled"
    assert snapshot["content"] == ""


def test_chat_stream_job_cancel_unknown_job_returns_false() -> None:
    store = ChatStreamJobStore()

    assert store.cancel("missing-job") is False
