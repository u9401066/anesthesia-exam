"""Helpers for Streamlit chat panel state and user-facing presentation."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from src.presentation.streamlit.async_chat import ChatStreamJobStore

CHAT_STREAM_STORE_KEY = "_chat_stream_jobs"
CHAT_JOB_NOT_FOUND_ERROR = "chat job not found"
STREAM_TARGET_MISSING_ERROR = "stream target message missing"


def ensure_chat_stream_job_store(session_state: MutableMapping[str, Any]) -> ChatStreamJobStore:
    """Reuse one in-memory job store per Streamlit session across reruns."""
    store = session_state.get(CHAT_STREAM_STORE_KEY)
    if isinstance(store, ChatStreamJobStore):
        return store

    store = ChatStreamJobStore()
    session_state[CHAT_STREAM_STORE_KEY] = store
    return store


def build_chat_stream_error_message(error_message: str) -> str:
    """Translate internal stream errors into stable, user-friendly copy."""
    normalized = str(error_message or "").strip()
    lowered = normalized.lower()

    if not normalized:
        return "[錯誤] 聊天串流失敗，請重試。"
    if lowered == CHAT_JOB_NOT_FOUND_ERROR:
        return "[錯誤] 背景回應已中斷，請重新送出一次。"
    if lowered == STREAM_TARGET_MISSING_ERROR:
        return "[錯誤] 對話畫面已更新，請重新送出一次。"
    return f"[錯誤] {normalized}"


def compute_chat_history_height(message_count: int) -> int:
    """Keep short conversations compact while leaving room for longer streams."""
    clamped_count = max(0, int(message_count))
    return min(420, max(240, 220 + min(clamped_count, 4) * 72))


def is_missing_chat_job_error(error_message: str) -> bool:
    """Return whether the store no longer knows about a requested job id."""
    return str(error_message or "").strip().lower() == CHAT_JOB_NOT_FOUND_ERROR
