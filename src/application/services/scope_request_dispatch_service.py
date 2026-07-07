"""Dispatch scope requests directly to an MCP-capable agent provider."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from src.application.services.exam_tool_application_service import ExamToolApplicationService
from src.application.services.heartbeat_service import CoverageGap, HeartbeatService
from src.application.services.openclaw_session_keys import build_openclaw_session_key
from src.domain.entities.scope_request import ScopeRequestStatus
from src.domain.value_objects.answer import coerce_question_type
from src.infrastructure.agent.provider import extract_last_json_object
from src.infrastructure.logging import get_logger
from src.infrastructure.persistence import get_question_repository
from src.infrastructure.persistence.sqlite_scope_request_repo import get_scope_request_repository

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXAMS_DIR = PROJECT_ROOT / "data" / "exams"
QUESTIONS_DIR = PROJECT_ROOT / "data" / "questions"


class AgentProviderLike(Protocol):
    """Minimal agent provider surface needed for request dispatch."""

    name: str

    def run(self, prompt: str, session_key: str | None = None) -> str: ...


class QuestionToolLike(Protocol):
    """Minimal question-tool surface needed for fallback persistence."""

    def save_question(self, args: dict) -> dict: ...


def _build_question_tool_service() -> ExamToolApplicationService:
    """Create a question tool adapter for fallback persistence."""
    return ExamToolApplicationService(
        repo=get_question_repository(),
        project_root=PROJECT_ROOT,
        exams_dir=EXAMS_DIR,
        questions_dir=QUESTIONS_DIR,
    )


@dataclass
class ScopeRequestDispatchResult:
    """Result of dispatching one scope request to an agent."""

    request_id: str
    provider_name: str
    generated_count: int = 0
    applied_count: int = 0
    question_ids: list[str] = field(default_factory=list)
    summary: str = ""
    raw_response: str = ""

    @property
    def success(self) -> bool:
        return self.generated_count > 0

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "provider_name": self.provider_name,
            "generated_count": self.generated_count,
            "applied_count": self.applied_count,
            "question_ids": list(self.question_ids),
            "summary": self.summary,
            "raw_response": self.raw_response,
            "success": self.success,
        }


class ScopeRequestDispatchService:
    """Run approved scope requests immediately through a connected agent provider."""

    def __init__(
        self,
        *,
        scope_repo=None,
        heartbeat: HeartbeatService | None = None,
        question_tool: QuestionToolLike | None = None,
    ) -> None:
        self.scope_repo = scope_repo or get_scope_request_repository()
        self.heartbeat = heartbeat or HeartbeatService()
        self.question_tool = question_tool or _build_question_tool_service()

    def build_dispatch_prompt(self, request_id: str) -> str:
        request = self.scope_repo.get_by_id(request_id)
        if request is None:
            raise ValueError(f"找不到出題需求：{request_id}")

        remaining = max(request.target_count - request.fulfilled_count, 0)
        if remaining <= 0:
            raise ValueError(f"需求 {request_id} 已達成，不需要再補題")

        gap = CoverageGap(
            topic=request.topic,
            current_count=request.fulfilled_count,
            target_count=request.target_count,
            deficit=remaining,
            difficulty=request.difficulty,
            exam_track=request.exam_track,
            source_request_id=request.id,
        )

        parts = [self.heartbeat.build_generation_prompt(gap)]
        if request.chapter:
            parts.append(f"- 章節 / 範圍：{request.chapter}")
        if request.reason:
            parts.append(f"- 補題原因：{request.reason}")

        parts.extend(
            [
                "",
                "補充規則：",
                "- 僅能使用 MCP 工具取得知識與來源，不可自行編造 citation。",
                "- 若 consult_knowledge_graph 暫時不可用，請改用 list_documents / fetch_document_asset / get_section_content / search_source_location 等工具完成。",
                "- 每生成一題都要立刻呼叫 exam_save_question 寫回題庫。",
                "- 完成後不要輸出長文；最後只輸出 JSON。",
                "",
                "JSON schema:",
                json.dumps(
                    {
                        "request_id": request.id,
                        "saved_count": remaining,
                        "question_ids": ["question_id_1"],
                        "summary": "一句話摘要",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        )
        return "\n".join(parts)

    def dispatch(
        self,
        request_id: str,
        provider: AgentProviderLike,
        *,
        session_key: str | None = None,
    ) -> ScopeRequestDispatchResult:
        request = self.scope_repo.get_by_id(request_id)
        if request is None:
            raise ValueError(f"找不到出題需求：{request_id}")
        if request.status == ScopeRequestStatus.REJECTED:
            raise ValueError(f"需求 {request_id} 已被駁回，不能派工")
        if request.status == ScopeRequestStatus.FULFILLED:
            raise ValueError(f"需求 {request_id} 已完成，不能重複派工")
        if request.status not in {ScopeRequestStatus.APPROVED, ScopeRequestStatus.IN_PROGRESS}:
            raise ValueError(f"需求 {request_id} 當前狀態 {request.status.value} 不允許派工")

        previous_status = request.status
        prompt = self.build_dispatch_prompt(request_id)
        resolved_session_key = session_key or build_openclaw_session_key("scope", request_id)
        self.scope_repo.update_status(request.id, ScopeRequestStatus.IN_PROGRESS)

        try:
            raw_response = provider.run(prompt, session_key=resolved_session_key).strip()
            payload = self._extract_payload(raw_response)
            question_ids = self._extract_question_ids(payload)
            embedded_question_payloads = self._extract_question_payloads(payload)
            if not question_ids:
                question_ids = self._persist_question_payloads(payload, getattr(provider, "name", "unknown"))
            generated_count = self._extract_generated_count(payload, question_ids)
            if embedded_question_payloads and not question_ids:
                generated_count = 0
            remaining = max(request.target_count - request.fulfilled_count, 0)
            applied_count = min(generated_count, remaining)
            summary = self._extract_summary(payload, raw_response, generated_count)

            if applied_count > 0:
                self.scope_repo.increment_fulfilled(request.id, applied_count)

            refreshed = self.scope_repo.get_by_id(request.id)
            next_status = refreshed.status if refreshed is not None else ScopeRequestStatus.IN_PROGRESS
            self.scope_repo.update_status(request.id, next_status, admin_notes=summary or None)

            result = ScopeRequestDispatchResult(
                request_id=request.id,
                provider_name=getattr(provider, "name", "unknown"),
                generated_count=generated_count,
                applied_count=applied_count,
                question_ids=question_ids,
                summary=summary,
                raw_response=raw_response,
            )
            logger.info(
                "scope_request_dispatched",
                request_id=request.id,
                provider_name=result.provider_name,
                generated_count=generated_count,
                applied_count=applied_count,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            self.scope_repo.update_status(request.id, previous_status, admin_notes=f"派工失敗：{exc}")
            logger.error(
                "scope_request_dispatch_failed",
                request_id=request.id,
                provider_name=getattr(provider, "name", "unknown"),
                error=str(exc),
            )
            raise

    def _extract_payload(self, raw_response: str) -> dict:
        stripped = raw_response.strip()
        if not stripped:
            return {}

        for candidate in self._candidate_json_blocks(stripped):
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload

        payload = extract_last_json_object(stripped)
        return payload if isinstance(payload, dict) else {}

    def _candidate_json_blocks(self, raw_response: str) -> list[str]:
        candidates = [raw_response]
        fenced_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, flags=re.DOTALL)
        candidates.extend(reversed(fenced_blocks))
        return candidates

    def _extract_question_ids(self, payload: dict) -> list[str]:
        for key in ("question_ids", "saved_question_ids"):
            value = payload.get(key)
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
        return []

    def _extract_generated_count(self, payload: dict, question_ids: list[str]) -> int:
        for key in ("saved_count", "generated_count", "count"):
            value = payload.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return max(int(value), len(question_ids))
            if isinstance(value, str) and value.strip().isdigit():
                return max(int(value.strip()), len(question_ids))
        return len(question_ids)

    def _persist_question_payloads(self, payload: dict, provider_name: str) -> list[str]:
        saved_ids: list[str] = []
        for question_payload in self._extract_question_payloads(payload):
            save_args = self._normalize_question_payload(question_payload, provider_name)
            if save_args is None:
                continue

            save_result = self.question_tool.save_question(save_args)
            if not save_result.get("success"):
                logger.warning(
                    "scope_request_dispatch_fallback_save_rejected",
                    provider_name=provider_name,
                    error=save_result.get("error"),
                )
                continue

            question_id = str(save_result.get("question_id") or "").strip()
            if question_id:
                saved_ids.append(question_id)

        return saved_ids

    def _extract_question_payloads(self, payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            return []

        candidates: list[dict] = []

        if self._looks_like_question_payload(payload):
            candidates.append(payload)

        for key in ("question", "questions", "items"):
            value = payload.get(key)
            if isinstance(value, dict) and self._looks_like_question_payload(value):
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict) and self._looks_like_question_payload(item))

        return candidates

    def _looks_like_question_payload(self, payload: dict) -> bool:
        question_text = payload.get("question_text") or payload.get("question")
        correct_answer = payload.get("correct_answer") or payload.get("answer")
        options = payload.get("options")
        if not (str(question_text or "").strip() and str(correct_answer or "").strip()):
            return False

        question_type = coerce_question_type(payload.get("question_type"), fallback_pattern=payload.get("pattern"))
        if question_type in {"single_choice", "multiple_choice", "true_false", "image_based"}:
            return isinstance(options, list) and len(options) >= 2

        if question_type in {"fill_in_blank", "short_answer", "essay"}:
            return True

        # 保守退路：無法辨識題型時，仍需 options 存在才視為正式題目。
        return bool(isinstance(options, list) and options)

    def _normalize_question_payload(self, payload: dict, provider_name: str) -> dict | None:
        if not self._looks_like_question_payload(payload):
            return None

        if payload.get("preview_only") is True:
            logger.info(
                "scope_request_dispatch_payload_skipped_preview_only",
                request_id=payload.get("request_id") or payload.get("requestId"),
                provider_name=provider_name,
            )
            return None

        formal_save_ready = payload.get("formal_save_ready")
        if formal_save_ready is False:
            logger.info(
                "scope_request_dispatch_payload_skipped_not_formal",
                request_id=payload.get("request_id") or payload.get("requestId"),
                provider_name=provider_name,
            )
            return None

        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        semantic_structure = payload.get("semantic_structure") if isinstance(payload.get("semantic_structure"), dict) else {}
        question_group = semantic_structure.get("question_group") if isinstance(semantic_structure.get("question_group"), dict) else {}

        question_type = coerce_question_type(payload.get("question_type"), fallback_pattern=payload.get("pattern"))
        difficulty = str(payload.get("difficulty") or "medium").strip().lower()
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"
        raw_topic_value = payload.get("topics")
        topics = [str(item).strip() for item in raw_topic_value if str(item).strip()] if isinstance(raw_topic_value, list) else []

        raw_options = payload.get("options")
        options = []
        if question_type in {"single_choice", "multiple_choice", "true_false", "image_based"}:
            if isinstance(raw_options, list):
                options = [str(item).strip() for item in raw_options if str(item).strip()]
        else:
            options = []

        return {
            "question_text": str(payload.get("question_text") or payload.get("question") or "").strip(),
            "options": options,
            "correct_answer": str(payload.get("correct_answer") or payload.get("answer") or "").strip(),
            "explanation": str(payload.get("explanation") or "").strip(),
            "difficulty": difficulty,
            "topics": topics,
            "pattern": payload.get("pattern") or question_group.get("pattern"),
            "question_type": question_type,
            "source_doc": payload.get("source_doc") or source.get("document"),
            "source_chapter": payload.get("source_chapter") or source.get("chapter"),
            "source_section": payload.get("source_section") or source.get("section"),
            "stem_source": payload.get("stem_source") or source.get("stem_source"),
            "answer_source": payload.get("answer_source") or source.get("answer_source"),
            "explanation_sources": payload.get("explanation_sources") or source.get("explanation_sources") or [],
            "source_page": payload.get("source_page") or source.get("page"),
            "source_lines": payload.get("source_lines") or source.get("lines"),
            "source_text": payload.get("source_text") or source.get("original_text"),
            "actor_name": provider_name,
        }

    def _extract_summary(self, payload: dict, raw_response: str, generated_count: int) -> str:
        summary = payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        if generated_count > 0 and self._extract_question_payloads(payload):
            return f"代理已回傳題目，系統補存 {generated_count} 題到題庫。"
        return raw_response.strip()[:400]


_service: ScopeRequestDispatchService | None = None


def get_scope_request_dispatch_service() -> ScopeRequestDispatchService:
    """Return the singleton scope-request dispatch service."""
    global _service
    if _service is None:
        _service = ScopeRequestDispatchService()
    return _service
