"""Structlog 配置

JSON 格式 + Console 彩色輸出雙軌日誌。
- 開發模式：Console 彩色 + JSON 檔案
- 生產模式：JSON 到 stdout + JSON 檔案
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def configure_logging(
    log_dir: Path | None = None,
    level: str = "INFO",
    json_console: bool = False,
) -> None:
    """初始化結構化 logging

    Args:
        log_dir: 日誌檔案目錄，None 則不寫檔
        level: 日誌等級 (DEBUG/INFO/WARNING/ERROR)
        json_console: Console 輸出是否用 JSON 格式
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # --- stdlib logging 處理器 ---
    handlers: list[logging.Handler] = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    handlers.append(console_handler)

    # File handler（JSON 格式）
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

        # MCP 專用日誌
        mcp_handler = logging.FileHandler(log_dir / "mcp.log", encoding="utf-8")
        mcp_handler.setLevel(logging.DEBUG)
        mcp_logger = logging.getLogger("mcp_trace")
        mcp_logger.addHandler(mcp_handler)
        mcp_logger.setLevel(logging.DEBUG)
        mcp_logger.propagate = True  # 也寫入 app.log

    # --- structlog 共用處理器 chain ---
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
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

    # --- stdlib root logger ---
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        foreign_pre_chain=shared_processors,
    )

    for handler in handlers:
        handler.setFormatter(formatter)

    # MCP handler 也套用 JSON formatter
    if log_dir:
        for h in logging.getLogger("mcp_trace").handlers:
            h.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """取得結構化 logger

    Usage:
        logger = get_logger(__name__)
        logger.info("tool_called", tool="exam_save_question", duration_ms=123)
    """
    return structlog.get_logger(name)
