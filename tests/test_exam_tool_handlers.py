import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.mcp.exam_tool_handlers import build_tool_handler_registry, dispatch_tool  # noqa: E402


class _FakeAppService:
    def save_question(self, args: dict) -> dict:
        return {"success": True, "tool": "save", "args": args}

    def list_questions(self, args: dict) -> dict:
        return {"tool": "list", "args": args}

    def create_exam(self, args: dict) -> dict:
        return {"tool": "create_exam", "args": args}

    def get_stats(self, args: dict | None = None) -> dict:
        return {"tool": "stats", "args": args or {}}

    def get_question(self, args: dict) -> dict:
        return {"tool": "get_question", "args": args}

    def delete_question(self, args: dict) -> dict:
        return {"tool": "delete", "args": args}

    def validate_question(self, args: dict) -> dict:
        return {"tool": "validate", "args": args}

    def update_question(self, args: dict) -> dict:
        return {"tool": "update", "args": args}

    def get_audit_log(self, args: dict) -> dict:
        return {"tool": "audit", "args": args}

    def mark_validated(self, args: dict) -> dict:
        return {"tool": "mark_validated", "args": args}

    def search_questions(self, args: dict) -> dict:
        return {"tool": "search", "args": args}

    def restore_question(self, args: dict) -> dict:
        return {"tool": "restore", "args": args}

    def bulk_save(self, args: dict) -> dict:
        return {"tool": "bulk_save", "args": args}


def test_dispatch_tool_uses_application_handler_registry() -> None:
    registry = build_tool_handler_registry(
        app_service=_FakeAppService(),
        legacy_handlers={"exam_get_pipeline_blueprint": lambda args: {"tool": "pipeline", "args": args}},
    )

    result = dispatch_tool("exam_save_question", {"question_text": "x"}, registry)

    assert result["success"] is True
    assert result["tool"] == "save"
    assert result["args"]["question_text"] == "x"


def test_dispatch_tool_returns_unknown_tool_error() -> None:
    result = dispatch_tool("exam_missing", {}, {})

    assert result == {"error": "Unknown tool: exam_missing"}