"""結構化 Logging 模組

提供 JSON 格式的結構化日誌，用於監控：
- Agent ↔ MCP 工具調用追蹤
- 生成流程計時與錯誤追蹤
- 效能指標記錄
"""

from src.infrastructure.logging.setup import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
