"""Stable OpenClaw session-key helpers for multi-user site entrypoints."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_SAFE_PART_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def normalize_openclaw_session_part(value: Any, *, fallback: str = "none", max_length: int = 72) -> str:
    """Normalize one value so it is safe and compact inside an OpenClaw session-key."""
    text = str(value or "").strip()
    if not text:
        text = fallback
    normalized = _SAFE_PART_RE.sub("-", text).strip("-._")
    if not normalized:
        normalized = fallback
    if len(normalized) <= max_length:
        return normalized
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    prefix = normalized[: max(1, max_length - len(digest) - 1)].strip("-._")
    return f"{prefix}-{digest}" if prefix else digest


def build_openclaw_session_key(kind: str, *parts: Any, agent_id: str = "main") -> str:
    """Build a stable session-key without ever falling back to agent:<id>:main."""
    safe_agent = normalize_openclaw_session_part(agent_id, fallback="main", max_length=48)
    safe_kind = normalize_openclaw_session_part(kind, fallback="site", max_length=48)
    safe_parts = [
        normalize_openclaw_session_part(part, fallback="none", max_length=72)
        for part in parts
        if str(part or "").strip()
    ]
    return ":".join(["agent", safe_agent, safe_kind, *safe_parts])
