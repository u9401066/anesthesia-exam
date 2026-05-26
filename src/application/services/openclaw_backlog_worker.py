"""Background worker for OpenClaw-driven question backlog processing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.application.services.heartbeat_service import HeartbeatService
from src.application.services.scope_request_dispatch_service import ScopeRequestDispatchService
from src.infrastructure.agent.provider import extract_last_json_object
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class AgentProviderLike(Protocol):
    """Minimal provider interface needed by the backlog worker."""

    name: str

    def run(self, prompt: str) -> str: ...


@dataclass
class OpenClawBacklogWorkerResult:
    """Summary for one worker pass."""

    heartbeat: dict[str, Any] | None = None
    pending_jobs: int = 0
    processed_jobs: int = 0
    generated_questions: int = 0
    skipped_jobs: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "heartbeat": self.heartbeat,
            "pending_jobs": self.pending_jobs,
            "processed_jobs": self.processed_jobs,
            "generated_questions": self.generated_questions,
            "skipped_jobs": self.skipped_jobs,
            "errors": list(self.errors),
            "success": not self.errors,
        }


class OpenClawBacklogWorker:
    """Consume heartbeat jobs and dispatch approved scope requests to OpenClaw."""

    def __init__(
        self,
        *,
        heartbeat: HeartbeatService | None = None,
        dispatch_service: ScopeRequestDispatchService | None = None,
    ) -> None:
        self.heartbeat = heartbeat or HeartbeatService()
        self.dispatch_service = dispatch_service or ScopeRequestDispatchService()

    def run_once(
        self,
        *,
        provider: AgentProviderLike,
        max_jobs: int = 1,
        heartbeat_max_requests: int = 5,
        generate_jobs: bool = True,
        dry_run: bool = False,
        process_auto_jobs: bool = False,
    ) -> OpenClawBacklogWorkerResult:
        """Run one bounded worker pass."""
        result = OpenClawBacklogWorkerResult()

        if generate_jobs:
            heartbeat_result = self.heartbeat.run_heartbeat(
                max_requests=max(0, heartbeat_max_requests),
                dry_run=dry_run,
            )
            result.heartbeat = heartbeat_result.to_dict()

        pending_jobs = self.heartbeat.list_jobs(status="pending")
        result.pending_jobs = len(pending_jobs)

        if dry_run:
            result.skipped_jobs = len(pending_jobs)
            logger.info("openclaw_backlog_worker_dry_run", pending_jobs=len(pending_jobs))
            return result

        jobs_to_consider = pending_jobs[: max(0, max_jobs)]
        result.skipped_jobs += max(0, len(pending_jobs) - len(jobs_to_consider))

        for job in jobs_to_consider:
            if not str(job.get("source_request_id") or "").strip() and not process_auto_jobs:
                result.skipped_jobs += 1
                logger.info("openclaw_backlog_worker_auto_job_skipped", job_id=job.get("job_id"), topic=job.get("topic"))
                continue

            try:
                generated = self._process_job(job, provider)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                result.errors.append(error)
                self._mark_error(job, error)
                logger.exception("openclaw_backlog_worker_job_failed", job_id=job.get("job_id"), error=error)
                continue

            result.processed_jobs += 1
            result.generated_questions += generated
            self.heartbeat.mark_job_done(self._job_path(job), questions_generated=generated)

        logger.info(
            "openclaw_backlog_worker_complete",
            pending_jobs=result.pending_jobs,
            processed_jobs=result.processed_jobs,
            generated_questions=result.generated_questions,
            error_count=len(result.errors),
        )
        return result

    def _process_job(self, job: dict[str, Any], provider: AgentProviderLike) -> int:
        request_id = str(job.get("source_request_id") or "").strip()
        if request_id:
            dispatch_result = self.dispatch_service.dispatch(request_id, provider)
            generated = max(0, int(getattr(dispatch_result, "generated_count", 0) or 0))
            if generated <= 0:
                raise ValueError("OpenClaw dispatch completed without saved_count > 0")
            return generated

        raw_response = provider.run(self._build_job_prompt(job)).strip()
        payload = extract_last_json_object(raw_response)
        if not isinstance(payload, dict):
            payload = self._extract_fenced_json(raw_response) or {}
        generated = self._generated_count(payload)
        if generated <= 0:
            summary = str(payload.get("summary") or raw_response[:200] or "no summary").strip()
            raise ValueError(f"OpenClaw job did not report saved_count > 0: {summary}")
        return generated

    def _build_job_prompt(self, job: dict[str, Any]) -> str:
        base_prompt = str(job.get("prompt") or "").strip()
        return "\n".join(
            [
                base_prompt,
                "",
                "執行規則：",
                "- 你是本網站的 OpenClaw 考題管理員。",
                "- 本輪只處理 1 題；不要試圖一次補完整個 deficit。",
                "- 教材型正式出題必須先使用 asset-aware MCP 取得來源，再使用 exam-generator MCP 寫回題庫。",
                "- 使用 OpenClaw 實際工具名稱：asset-aware__consult_knowledge_graph、asset-aware__search_source_location、exam-generator__exam_save_question。",
                "- 不要呼叫 asset-aware__inspect_document_manifest 讀取大型 manifest；要先用 asset-aware__list_documents 找最相關的分章 doc_id，再做精準搜尋。",
                "- 如果 asset-aware__consult_knowledge_graph 不可用，改用 asset-aware__search_source_location / asset-aware__get_section_content / asset-aware__fetch_document_asset。",
                "- 不可自行編造 citation；缺少精確來源時要停止並回報。",
                "- 找到足夠 evidence 後，直接呼叫 exam-generator__exam_save_question；不要先輸出計畫、草稿或「我將開始生成」。",
                "- 若無法保存至少 1 題，最後仍輸出 JSON，saved_count 必須是 0，summary 以 blocked: 開頭說明原因。",
                "- 完成後不要輸出長文；最後只輸出 JSON。",
                "",
                "JSON schema:",
                json.dumps(
                    {
                        "saved_count": 1,
                        "question_ids": ["question_id"],
                        "summary": "一句話摘要",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        )

    @staticmethod
    def _extract_fenced_json(raw_response: str) -> dict[str, Any] | None:
        start = raw_response.rfind("{")
        end = raw_response.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            payload = json.loads(raw_response[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _generated_count(payload: dict[str, Any]) -> int:
        for key in ("saved_count", "generated_count", "applied_count"):
            value = payload.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return max(0, value)
            if isinstance(value, str) and value.strip().isdigit():
                return max(0, int(value.strip()))

        question_ids = payload.get("question_ids") or payload.get("saved_question_ids")
        if isinstance(question_ids, list):
            return len([item for item in question_ids if str(item).strip()])
        return 0

    def _mark_error(self, job: dict[str, Any], error: str) -> None:
        try:
            self.heartbeat.mark_job_error(self._job_path(job), error)
        except Exception:  # noqa: BLE001
            logger.exception("openclaw_backlog_worker_mark_error_failed", job_id=job.get("job_id"))

    def _job_path(self, job: dict[str, Any]) -> Path:
        raw_path = str(job.get("_path") or "").strip()
        if raw_path:
            return Path(raw_path)
        job_id = str(job.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("pending job missing _path and job_id")
        return self.heartbeat.jobs_dir / f"{job_id}.json"
