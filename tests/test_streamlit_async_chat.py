import time
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.presentation.streamlit.async_chat import ChatStreamJobStore
from src.presentation.streamlit.chat_panel import (
    build_chat_stream_error_message,
    compute_chat_history_height,
    ensure_chat_stream_job_store,
)


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


def test_chat_stream_job_store_is_reused_within_same_session_state() -> None:
    session_state: dict[str, object] = {}

    first = ensure_chat_stream_job_store(session_state)
    second = ensure_chat_stream_job_store(session_state)

    assert first is second
    assert session_state["_chat_stream_jobs"] is first


def test_chat_stream_job_store_replaces_invalid_session_state_value() -> None:
    session_state: dict[str, object] = {"_chat_stream_jobs": "broken"}

    store = ensure_chat_stream_job_store(session_state)

    assert isinstance(store, ChatStreamJobStore)
    assert session_state["_chat_stream_jobs"] is store


def test_chat_stream_error_message_hides_internal_missing_job_marker() -> None:
    message = build_chat_stream_error_message("chat job not found")

    assert message.startswith("[錯誤]")
    assert "chat job not found" not in message
    assert "重新送出" in message


def test_chat_history_height_stays_compact_for_short_conversations() -> None:
    assert compute_chat_history_height(0) == 240
    assert compute_chat_history_height(2) == 364
    assert compute_chat_history_height(20) == 420
