"""Structlog 配置與共用 bootstrap。"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Generator

import structlog

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR_ENV_VAR = "ANESTHESIA_EXAM_LOG_DIR"
LOG_LEVEL_ENV_VAR = "ANESTHESIA_EXAM_LOG_LEVEL"
LOG_JSON_CONSOLE_ENV_VAR = "ANESTHESIA_EXAM_LOG_JSON_CONSOLE"
LOG_MAX_BYTES_ENV_VAR = "ANESTHESIA_EXAM_LOG_MAX_BYTES"
LOG_BACKUP_COUNT_ENV_VAR = "ANESTHESIA_EXAM_LOG_BACKUP_COUNT"
DEBUG_ENV_VAR = "ANESTHESIA_EXAM_DEBUG"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5

_BOOTSTRAP_SIGNATURE: tuple[str | None, str, bool, int, int] | None = None


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Resolved logging configuration after env overrides."""

    log_dir: Path | None
    level: str
    json_console: bool
    max_bytes: int
    backup_count: int


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "debug"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(int(value), 1)
    except ValueError:
        return default


def resolve_logging_config(
    log_dir: Path | None = None,
    level: str | None = None,
    json_console: bool | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> LoggingConfig:
    """Resolve log settings from explicit arguments first, then env vars."""
    resolved_log_dir = log_dir
    if resolved_log_dir is None:
        env_log_dir = os.getenv(LOG_DIR_ENV_VAR)
        resolved_log_dir = Path(env_log_dir) if env_log_dir else DEFAULT_LOG_DIR

    resolved_level = (level or os.getenv(LOG_LEVEL_ENV_VAR) or "").strip().upper()
    if not resolved_level:
        resolved_level = "DEBUG" if _env_flag(DEBUG_ENV_VAR) else "INFO"

    resolved_json_console = json_console if json_console is not None else _env_flag(LOG_JSON_CONSOLE_ENV_VAR, False)
    resolved_max_bytes = max_bytes if max_bytes is not None else _env_int(LOG_MAX_BYTES_ENV_VAR, DEFAULT_MAX_BYTES)
    resolved_backup_count = (
        backup_count if backup_count is not None else _env_int(LOG_BACKUP_COUNT_ENV_VAR, DEFAULT_BACKUP_COUNT)
    )

    return LoggingConfig(
        log_dir=Path(resolved_log_dir) if resolved_log_dir else None,
        level=resolved_level,
        json_console=resolved_json_console,
        max_bytes=resolved_max_bytes,
        backup_count=resolved_backup_count,
    )


def configure_logging(
    log_dir: Path | None = None,
    level: str = "INFO",
    json_console: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> None:
    """初始化結構化 logging。"""
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_renderer: structlog.types.Processor
    if json_console:
        console_renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        console_renderer = structlog.dev.ConsoleRenderer(colors=False)

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
        foreign_pre_chain=shared_processors,
    )
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        foreign_pre_chain=shared_processors,
    )

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)
    handlers.append(console_handler)

    mcp_logger = logging.getLogger("mcp_trace")
    mcp_logger.handlers.clear()
    mcp_logger.setLevel(logging.DEBUG)
    mcp_logger.propagate = True

    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(json_formatter)
        handlers.append(file_handler)

        mcp_handler = RotatingFileHandler(
            log_dir / "mcp.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        mcp_handler.setLevel(logging.DEBUG)
        mcp_handler.setFormatter(json_formatter)
        mcp_logger.addHandler(mcp_handler)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def bootstrap_logging(
    app_name: str,
    *,
    log_dir: Path | None = None,
    level: str | None = None,
    json_console: bool | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
    extra_context: dict[str, Any] | None = None,
) -> structlog.stdlib.BoundLogger:
    """Idempotent bootstrap used by web, MCP, scripts and CLI entrypoints."""
    global _BOOTSTRAP_SIGNATURE

    config = resolve_logging_config(
        log_dir=log_dir,
        level=level,
        json_console=json_console,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
    signature = (
        str(config.log_dir) if config.log_dir else None,
        config.level,
        config.json_console,
        config.max_bytes,
        config.backup_count,
    )
    if _BOOTSTRAP_SIGNATURE != signature:
        configure_logging(
            log_dir=config.log_dir,
            level=config.level,
            json_console=config.json_console,
            max_bytes=config.max_bytes,
            backup_count=config.backup_count,
        )
        _BOOTSTRAP_SIGNATURE = signature

    structlog.contextvars.clear_contextvars()
    bind_log_context(app=app_name)
    if extra_context:
        bind_log_context(**extra_context)

    logger = get_logger(app_name)
    logger.info(
        "logging_bootstrap_configured",
        level=config.level,
        log_dir=str(config.log_dir) if config.log_dir else None,
        json_console=config.json_console,
        max_bytes=config.max_bytes,
        backup_count=config.backup_count,
    )
    return logger


def bind_log_context(**kwargs: Any) -> dict[str, Any]:
    """Bind non-empty contextvars so downstream logs inherit run metadata."""
    payload = {key: value for key, value in kwargs.items() if value not in (None, "", [], {}, ())}
    if payload:
        structlog.contextvars.bind_contextvars(**payload)
    return payload


def unbind_log_context(*keys: str) -> None:
    """Remove bound logging context keys if they exist."""
    if keys:
        structlog.contextvars.unbind_contextvars(*keys)


@contextmanager
def log_context(**kwargs: Any) -> Generator[None, None, None]:
    """Temporarily bind logging context within a code block."""
    payload = bind_log_context(**kwargs)
    try:
        yield
    finally:
        if payload:
            unbind_log_context(*payload.keys())


def new_run_id(prefix: str = "run") -> str:
    """Generate short stable run ids for tracing multi-step workflows."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """取得結構化 logger。"""
    return structlog.get_logger(name)
