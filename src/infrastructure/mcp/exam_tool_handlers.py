"""Registry-based MCP tool handlers for the exam server."""

from __future__ import annotations

from collections.abc import Callable

from src.application.services.exam_tool_application_service import ExamToolApplicationService

ToolHandler = Callable[[dict], dict]


def build_tool_handler_registry(
    *,
    app_service: ExamToolApplicationService,
    legacy_handlers: dict[str, ToolHandler],
) -> dict[str, ToolHandler]:
    """Combine application-backed handlers with legacy server-side handlers."""
    registry: dict[str, ToolHandler] = {
        "exam_save_question": app_service.save_question,
        "exam_list_questions": app_service.list_questions,
        "exam_create_exam": app_service.create_exam,
        "exam_get_stats": app_service.get_stats,
        "exam_get_question": app_service.get_question,
        "exam_delete_question": app_service.delete_question,
        "exam_validate_question": app_service.validate_question,
        "exam_update_question": app_service.update_question,
        "exam_get_audit_log": app_service.get_audit_log,
        "exam_mark_validated": app_service.mark_validated,
        "exam_search": app_service.search_questions,
        "exam_restore_question": app_service.restore_question,
        "exam_bulk_save": app_service.bulk_save,
    }
    registry.update(legacy_handlers)
    return registry


def dispatch_tool(name: str, arguments: dict, registry: dict[str, ToolHandler]) -> dict:
    """Dispatch a tool call via the prepared registry."""
    handler = registry.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    return handler(arguments)