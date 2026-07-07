"""Registry-based MCP tool handlers for the exam server."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.application.services.exam_tool_application_service import ExamToolApplicationService

ToolHandler = Callable[[dict], dict]

_PHASE_STATUSES = {"not_started", "in_progress", "completed", "blocked", "failed"}
PIPELINE_STATUSES = {"active", "completed", "blocked", "failed"}
PIPELINE_TYPES = {"exam-generation", "past-exam-extraction"}


def _coerce_int_argument(
    value: Any,
    *,
    field: str,
    default: int,
    min_value: int = 1,
    max_value: int = 1000,
) -> tuple[int, str | None]:
    if value is None:
        return default, None

    if isinstance(value, bool):
        return default, f"{field} 不能是布林值"

    if isinstance(value, int):
        candidate = value
    elif isinstance(value, float):
        candidate = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return default, f"{field} 為空"
        try:
            candidate = int(text)
        except ValueError:
            return default, f"{field} 必須是數字（收到 {value!r}）"
    else:
        return default, f"{field} 類型不合法"

    if candidate < min_value:
        return default, f"{field} 需 >= {min_value}"
    if candidate > max_value:
        return default, f"{field} 需 <= {max_value}"
    return candidate, None


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    parsed: list[str] = []
    for item in value:
        text = str(item).strip() if item is not None else ""
        if text:
            parsed.append(text)
    return parsed


def _validate_dispatch(name: str, arguments: dict) -> tuple[dict, str | None]:
    normalized = dict(arguments)

    if name == "exam_start_pipeline_run":
        target, error = _coerce_int_argument(
            normalized.get("target_question_count"),
            field="target_question_count",
            default=10,
            min_value=1,
            max_value=2000,
        )
        if error:
            return normalized, error
        normalized["target_question_count"] = target

        name_value = _coerce_optional_str(normalized.get("name"))
        if not name_value:
            return normalized, "name 為必填欄位且不可為空"
        normalized["name"] = name_value

        objective = _coerce_optional_str(normalized.get("objective"))
        if not objective:
            return normalized, "objective 為必填欄位且不可為空"
        normalized["objective"] = objective

        pipeline_type = _coerce_optional_str(normalized.get("pipeline_type")) or "exam-generation"
        if pipeline_type not in PIPELINE_TYPES:
            return normalized, f"pipeline_type 僅接受 {sorted(PIPELINE_TYPES)}"
        normalized["pipeline_type"] = pipeline_type

        if "source_doc_ids" in normalized:
            source_doc_ids = _coerce_string_list(normalized.get("source_doc_ids"))
            if not source_doc_ids:
                return normalized, "source_doc_ids 必須是字串陣列"
            normalized["source_doc_ids"] = source_doc_ids
        else:
            normalized["source_doc_ids"] = []

        notes = _coerce_optional_str(normalized.get("notes"))
        normalized["notes"] = notes

    if name == "exam_list_pipeline_runs":
        limit, error = _coerce_int_argument(
            normalized.get("limit"),
            field="limit",
            default=20,
            min_value=1,
            max_value=200,
        )
        if error:
            return normalized, error
        normalized["limit"] = limit

        status = _coerce_optional_str(normalized.get("status"))
        if status is not None and status not in PIPELINE_STATUSES:
            return normalized, f"status 必須是 {sorted(PIPELINE_STATUSES)}"

    if name in {"exam_get_audit_log", "exam_list_questions", "exam_search"}:
        limit, error = _coerce_int_argument(
            normalized.get("limit"),
            field="limit",
            default=20,
            min_value=1,
            max_value=500,
        )
        if error:
            return normalized, error
        normalized["limit"] = limit

    if name in {"exam_record_phase_result", "exam_validate_phase_gate", "exam_get_pipeline_run"}:
        run_id = _coerce_optional_str(normalized.get("run_id"))
        if not run_id:
            return normalized, "run_id 為必填欄位且不可為空"
        normalized["run_id"] = run_id

    if name == "exam_record_phase_result":
        status = _coerce_optional_str(normalized.get("status"))
        if status not in _PHASE_STATUSES:
            return normalized, f"status 必須是 {sorted(_PHASE_STATUSES)}"
        normalized["status"] = status

        artifacts = normalized.get("artifacts")
        if artifacts is not None and not isinstance(artifacts, dict):
            return normalized, "artifacts 必須是物件"

        metrics = normalized.get("metrics")
        if metrics is not None and not isinstance(metrics, dict):
            return normalized, "metrics 必須是物件"

        if normalized.get("summary") is not None and not isinstance(normalized.get("summary"), str):
            return normalized, "summary 必須是字串"
        if normalized.get("next_action") is not None and not isinstance(normalized.get("next_action"), str):
            return normalized, "next_action 必須是字串"

        phase_key = _coerce_optional_str(normalized.get("phase_key"))
        if not phase_key:
            return normalized, "phase_key 為必填欄位且不可為空"
        normalized["phase_key"] = phase_key

    if name == "exam_validate_phase_gate":
        phase_key = _coerce_optional_str(normalized.get("phase_key"))
        if not phase_key:
            return normalized, "phase_key 為必填欄位且不可為空"
        normalized["phase_key"] = phase_key

    if name == "exam_run_past_exam_extraction":
        doc_id = _coerce_optional_str(normalized.get("doc_id"))
        if not doc_id:
            return normalized, "doc_id 為必填欄位且不可為空"
        normalized["doc_id"] = doc_id

    return normalized, None


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
    if not isinstance(arguments, dict):
        return {"error": "arguments 必須是 JSON 物件"}

    arguments = dict(arguments)
    normalized, error = _validate_dispatch(name, arguments)
    if error:
        return {"error": error}

    handler = registry.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}

    try:
        result = handler(normalized)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"處理 {name} 時發生錯誤: {exc}"}

    if not isinstance(result, dict):
        return {"error": f"tool {name} 回傳格式不正確，預期 dict"}
    return result
