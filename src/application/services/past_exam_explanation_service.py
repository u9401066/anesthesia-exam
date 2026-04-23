"""Generate and persist past-exam explanations using repo context and an LLM."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from src.application.services.past_exam_extraction_service import PastExamExtractionService
from src.application.services.textbook_generation_service import TextbookGenerationService
from src.infrastructure.agent import collect_opencode_available_models
from src.infrastructure.agent.provider import extract_chat_completion_text, extract_responses_api_text
from src.infrastructure.logging import get_logger
from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OPENCODE_CONFIG_PATH = PROJECT_ROOT / "opencode.json"
logger = get_logger(__name__)

MATCH_STOPWORDS = {
    "about",
    "after",
    "among",
    "because",
    "between",
    "choice",
    "correct",
    "during",
    "following",
    "from",
    "goal",
    "incorrect",
    "option",
    "patient",
    "question",
    "regarding",
    "therapy",
    "these",
    "this",
    "those",
    "under",
    "which",
    "with",
}


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", " ", value)
    cleaned = cleaned.replace("`", " ")
    cleaned = re.sub(r"[_*#>\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def _truncate_text(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 0)].rstrip() + "..."


def _resolve_variable(value: str) -> str:
    stripped = str(value or "").strip()
    env_match = re.fullmatch(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}", stripped)
    if env_match:
        return os.getenv(env_match.group(1), "")
    return stripped


class PastExamExplanationService:
    """Find similar explained questions, generate rationale, and save it back."""

    def __init__(
        self,
        *,
        past_exam_repo=None,
        question_repo=None,
        data_dir: Path | None = None,
        textbook_generation_service: TextbookGenerationService | None = None,
        past_exam_extraction_service: PastExamExtractionService | None = None,
        opencode_config_path: Path | None = None,
        request_timeout: int = 120,
    ):
        self.past_exam_repo = past_exam_repo or get_past_exam_repository()
        self.question_repo = question_repo or get_question_repository()
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.textbook_generation_service = textbook_generation_service or TextbookGenerationService(self.data_dir)
        self.past_exam_extraction_service = past_exam_extraction_service or PastExamExtractionService(self.data_dir)
        self.opencode_config_path = opencode_config_path or DEFAULT_OPENCODE_CONFIG_PATH
        self.request_timeout = request_timeout
        self._cached_textbook_doc_catalog: list[dict[str, Any]] | None = None
        logger.debug(
            "past_exam_explanation_service_initialized",
            data_dir=str(self.data_dir),
            opencode_config_path=str(self.opencode_config_path),
            request_timeout=request_timeout,
        )

    def _empty_textbook_evidence_pack(self, reason: str) -> dict[str, Any]:
        """Return a stable no-evidence payload for UI and prompt callers."""
        return {
            "source_ready": False,
            "matched_doc_id": None,
            "matched_doc_title": None,
            "gate_reasons": [reason] if reason else [],
            "source": {},
        }

    def _normalize_textbook_evidence_pack(self, evidence_pack: Any) -> dict[str, Any]:
        """Coerce legacy or unexpected evidence payloads into the current dict shape."""
        if isinstance(evidence_pack, tuple):
            for item in evidence_pack:
                if isinstance(item, dict):
                    evidence_pack = item
                    break

        if not isinstance(evidence_pack, dict):
            return self._empty_textbook_evidence_pack("教材證據格式不支援")

        normalized = self._empty_textbook_evidence_pack("")
        normalized.update({key: value for key, value in evidence_pack.items() if key != "source"})
        source = evidence_pack.get("source")
        normalized["source"] = dict(source) if isinstance(source, dict) else {}
        normalized["source_ready"] = bool(normalized.get("source_ready"))
        gate_reasons = normalized.get("gate_reasons")
        if isinstance(gate_reasons, list):
            normalized["gate_reasons"] = [str(reason) for reason in gate_reasons if str(reason).strip()]
        elif gate_reasons:
            normalized["gate_reasons"] = [str(gate_reasons)]
        else:
            normalized["gate_reasons"] = []
        return normalized

    def get_generation_availability(self, provider=None) -> tuple[bool, str]:
        """Return whether explanation generation can run right now."""
        if provider is not None:
            return True, f"使用 provider: {getattr(provider, 'name', 'unknown')}"

        try:
            llm_config = self.resolve_direct_llm_config()
        except RuntimeError as exc:
            return False, str(exc)

        return True, f"直接呼叫 {llm_config['base_url']} 的 OpenAI-compatible endpoint"

    def find_reference_matches(self, question: dict, *, limit: int = 5) -> list[dict[str, Any]]:
        """Find explanation-bearing reference questions from the repo."""
        target_id = str(question.get("id") or "").strip()
        target_topics = {self._normalize_label(topic) for topic in question.get("topics", []) if topic}
        target_concepts = {
            self._normalize_label(name) for name in question.get("concept_names", []) if name
        }
        target_tokens = self._question_tokens(question)
        target_text = _normalize_text(self._question_search_text(question))

        candidates: list[dict[str, Any]] = []

        for regular_question in self.question_repo.list_all(limit=500):
            if not str(regular_question.explanation or "").strip():
                continue

            candidate_topics = {
                self._normalize_label(topic) for topic in (regular_question.topics or []) if topic
            }
            candidate_tokens = self._text_tokens(
                " ".join(
                    [
                        regular_question.question_text,
                        " ".join(regular_question.options or []),
                        " ".join(regular_question.topics or []),
                    ]
                )
            )
            score = self._similarity_score(
                target_tokens=target_tokens,
                target_topics=target_topics,
                target_concepts=target_concepts,
                target_text=target_text,
                candidate_tokens=candidate_tokens,
                candidate_topics=candidate_topics,
                candidate_concepts=set(),
                candidate_text=_normalize_text(regular_question.question_text),
            )
            if score <= 0:
                continue

            candidates.append(
                {
                    "source_type": "general_bank",
                    "source_id": regular_question.id,
                    "label": f"一般題庫｜{regular_question.id[:8]}",
                    "question_text": regular_question.question_text,
                    "correct_answer": regular_question.correct_answer,
                    "explanation": regular_question.explanation,
                    "topics": list(regular_question.topics or []),
                    "score": round(score, 4),
                }
            )

        for past_exam_question in self.past_exam_repo.list_all_questions(limit=2000, explanation_required=True):
            if past_exam_question.id == target_id:
                continue

            candidate_topics = {
                self._normalize_label(topic) for topic in (past_exam_question.topics or []) if topic
            }
            candidate_concepts = {
                self._normalize_label(name) for name in (past_exam_question.concept_names or []) if name
            }
            score = self._similarity_score(
                target_tokens=target_tokens,
                target_topics=target_topics,
                target_concepts=target_concepts,
                target_text=target_text,
                candidate_tokens=self._text_tokens(
                    " ".join(
                        [
                            past_exam_question.question_text,
                            " ".join(past_exam_question.options or []),
                            " ".join(past_exam_question.topics or []),
                            " ".join(past_exam_question.concept_names or []),
                        ]
                    )
                ),
                candidate_topics=candidate_topics,
                candidate_concepts=candidate_concepts,
                candidate_text=_normalize_text(past_exam_question.question_text),
            )
            if score <= 0:
                continue

            candidates.append(
                {
                    "source_type": "past_exam",
                    "source_id": past_exam_question.id,
                    "label": (
                        f"{past_exam_question.exam_year}｜{past_exam_question.exam_name}"
                        f" 第 {past_exam_question.question_number} 題"
                    ),
                    "question_text": past_exam_question.question_text,
                    "correct_answer": past_exam_question.correct_answer,
                    "explanation": past_exam_question.explanation,
                    "topics": list(past_exam_question.topics or []),
                    "score": round(score, 4),
                }
            )

        candidates.sort(key=lambda item: (item["score"], item["source_type"] == "general_bank"), reverse=True)
        return candidates[:limit]

    def list_textbook_doc_catalog(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """List source-ready textbook-like docs that can support explanation grounding."""
        if self._cached_textbook_doc_catalog is not None and not force_refresh:
            return list(self._cached_textbook_doc_catalog)

        configured_doc_ids = [
            doc_id.strip()
            for doc_id in str(os.getenv("EXAM_PAST_EXAM_TEXTBOOK_DOC_IDS") or "").split(",")
            if doc_id.strip()
        ]
        candidate_doc_ids = configured_doc_ids or sorted(
            doc_dir.name
            for doc_dir in self.data_dir.glob("doc_*")
            if doc_dir.is_dir()
        )

        catalog: list[dict[str, Any]] = []
        for doc_id in candidate_doc_ids:
            try:
                readiness = self.textbook_generation_service.assess_document_source_readiness(doc_id)
                if not readiness.get("source_ready"):
                    continue

                document = self.textbook_generation_service.asset_loader.load_asset_document(doc_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "past_exam_textbook_catalog_doc_skipped",
                    doc_id=doc_id,
                    error=str(exc),
                )
                continue

            filename = str(document.manifest.get("filename") or "")
            if not self._looks_like_textbook_document(document.title, filename):
                continue

            catalog.append(
                {
                    "doc_id": doc_id,
                    "title": document.title,
                    "filename": filename,
                    "readiness": readiness,
                }
            )

        catalog.sort(
            key=lambda item: (
                "miller" not in _normalize_text(f"{item.get('title', '')} {item.get('filename', '')}"),
                item.get("title", ""),
                item.get("doc_id", ""),
            )
        )
        self._cached_textbook_doc_catalog = list(catalog)
        logger.info(
            "past_exam_textbook_catalog_built",
            catalog_size=len(catalog),
            configured_doc_ids=configured_doc_ids,
        )
        return catalog

    def find_textbook_evidence(
        self,
        question: dict,
        *,
        doc_ids: list[str] | None = None,
        selected_sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Resolve precise textbook evidence for a past-exam question when available."""
        try:
            candidate_doc_ids = list(doc_ids or [doc["doc_id"] for doc in self.list_textbook_doc_catalog()])
            if not candidate_doc_ids:
                return self._empty_textbook_evidence_pack("目前沒有可用的 source-ready 教材文件")

            evidence_pack = self.textbook_generation_service.build_evidence_pack_for_question(
                question,
                selected_doc_ids=candidate_doc_ids,
                selected_sections=selected_sections,
            )
            normalized_pack = self._normalize_textbook_evidence_pack(evidence_pack)
            logger.info(
                "past_exam_textbook_evidence_resolved",
                question_id=question.get("id"),
                source_ready=bool(normalized_pack.get("source_ready")),
                matched_doc_id=normalized_pack.get("matched_doc_id"),
                candidate_doc_count=len(candidate_doc_ids),
            )
            return normalized_pack
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "past_exam_textbook_evidence_resolution_failed",
                question_id=question.get("id"),
                error=str(exc),
            )
            return self._empty_textbook_evidence_pack(f"教材證據解析失敗：{exc}")

    def safe_find_textbook_evidence(
        self,
        question: dict,
        *,
        doc_ids: list[str] | None = None,
        selected_sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Compatibility wrapper for UI callers that expect a non-throwing lookup."""
        return self.find_textbook_evidence(
            question,
            doc_ids=doc_ids,
            selected_sections=selected_sections,
        )

    def build_question_semantic_outline(self, question: dict) -> dict[str, Any]:
        """Build a reusable semantic outline for explanation and generation prompts."""
        return self.past_exam_extraction_service.build_question_semantic_outline(question)

    def build_generation_prompt(
        self,
        question: dict,
        references: list[dict[str, Any]],
        textbook_evidence: dict[str, Any] | None = None,
    ) -> str:
        """Build the LLM prompt used for explanation generation."""
        target_payload = {
            "question_text": question.get("question_text", ""),
            "options": question.get("options", []),
            "correct_answer": question.get("correct_answer", ""),
            "topics": question.get("topics", []),
            "concept_names": question.get("concept_names", []),
            "exam_year": question.get("exam_year"),
            "exam_name": question.get("exam_name"),
            "question_number": question.get("question_number"),
        }

        lines = [
            "你是麻醉專科考題助教，請為使用者撰寫一段繁體中文詳解。",
            "規則：",
            "- 若有教材證據，必須優先依教材證據撰寫，且只能引用提示中真的出現的教材資訊。",
            "- 先依題目結構骨架拆解：題組層、題幹層、各選項層，再開始寫詳解。",
            "- 先點出正確答案為何正確。",
            "- 逐一說明其他選項為何錯誤、較不完整，或臨床上較不恰當。",
            "- 若 repo 參考資料不足，可依麻醉學通則做保守推論，但不得捏造教材頁碼、文獻、研究名稱或不存在的來源。",
            "- 若教材證據不足或只部分命中，可以說明『依教材可確認到的重點』與『其餘為保守臨床推論』，但不可假裝有明確章節或頁碼。",
            "- 不要提到「參考題庫」、「第幾題」或任何內部工作流，只輸出給考生看的最終詳解。",
            "- 若有教材證據，詳解最後請補一行教材定位，格式為：教材定位：<書名>｜<章節>｜P.<頁碼> L<起>-<迄>。",
            "- 若沒有精確教材證據，不要輸出任何虛構的教材定位。",
            '- 請只輸出單一 JSON 物件，格式為 {"explanation":"..."}。',
            "",
            "目標題目：",
            json.dumps(target_payload, ensure_ascii=False, indent=2),
        ]
        semantic_outline = self.build_question_semantic_outline(question)
        lines.extend(
            [
                "",
                "題目結構骨架（請先依這份結構拆解，再撰寫詳解）：",
                json.dumps(semantic_outline, ensure_ascii=False, indent=2),
            ]
        )

        source_payload = (textbook_evidence or {}).get("source") or {}
        explanation_sources = list(source_payload.get("explanation_sources") or [])
        textbook_payload = {
            "source_ready": bool((textbook_evidence or {}).get("source_ready")),
            "matched_doc_title": (textbook_evidence or {}).get("matched_doc_title"),
            "matched_doc_id": (textbook_evidence or {}).get("matched_doc_id"),
            "chapter": source_payload.get("chapter"),
            "section": source_payload.get("section"),
            "stem_source": source_payload.get("stem_source"),
            "answer_source": source_payload.get("answer_source"),
            "explanation_sources": explanation_sources[:3],
            "gate_reasons": (textbook_evidence or {}).get("gate_reasons", []),
        }
        lines.extend(
            [
                "",
                "教材證據（優先依此撰寫，不得捏造引用）：",
                json.dumps(textbook_payload, ensure_ascii=False, indent=2),
            ]
        )

        if references:
            lines.extend(["", "可參考的題庫脈絡："])
            for index, reference in enumerate(references, start=1):
                lines.append(
                    json.dumps(
                        {
                            "reference": index,
                            "label": reference.get("label", ""),
                            "question_text": _truncate_text(str(reference.get("question_text") or ""), 220),
                            "correct_answer": reference.get("correct_answer", ""),
                            "topics": reference.get("topics", []),
                            "score": reference.get("score", 0.0),
                            "explanation": _truncate_text(str(reference.get("explanation") or ""), 420),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        else:
            lines.extend(
                [
                    "",
                    "目前沒有找到現成詳解參考，請主要依題目、選項、知識點與麻醉學基礎邏輯生成詳解。",
                ]
            )

        return "\n".join(lines)

    def generate_explanation(self, question: dict, *, provider=None, reference_limit: int = 5) -> dict[str, Any]:
        """Generate one explanation draft for a past-exam question."""
        references = self.find_reference_matches(question, limit=reference_limit)
        textbook_evidence = self.find_textbook_evidence(question)
        prompt = self.build_generation_prompt(question, references, textbook_evidence)
        raw_response = self._invoke_llm(prompt, provider=provider)
        explanation = self._extract_explanation(raw_response)
        if not explanation:
            raise RuntimeError("LLM 沒有產出可解析的 explanation")
        semantic_outline = self.build_question_semantic_outline(question)

        result = {
            "question_id": question.get("id"),
            "explanation": explanation,
            "reference_matches": references,
            "semantic_outline": semantic_outline,
            "textbook_evidence": textbook_evidence,
            "raw_response": raw_response,
        }
        logger.info(
            "past_exam_explanation_generated",
            question_id=question.get("id"),
            reference_count=len(references),
            textbook_source_ready=bool(textbook_evidence.get("source_ready")),
            explanation_len=len(explanation),
        )
        return result

    def generate_and_save_explanation(
        self,
        question: dict,
        *,
        provider=None,
        reference_limit: int = 5,
    ) -> dict[str, Any]:
        """Generate and persist one explanation."""
        result = self.generate_explanation(
            question,
            provider=provider,
            reference_limit=reference_limit,
        )
        saved = self.past_exam_repo.update_question_explanation(
            str(question.get("id") or ""),
            result["explanation"],
        )
        result["saved"] = saved
        return result

    def generate_and_save_missing_explanations(
        self,
        questions: list[dict],
        *,
        provider=None,
        limit: int = 3,
        reference_limit: int = 5,
    ) -> dict[str, Any]:
        """Generate explanations for up to `limit` missing rows."""
        generated: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for question in questions:
            if len(generated) >= limit:
                break
            if str(question.get("explanation") or "").strip():
                continue

            try:
                generated.append(
                    self.generate_and_save_explanation(
                        question,
                        provider=provider,
                        reference_limit=reference_limit,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "past_exam_explanation_generation_failed",
                    question_id=question.get("id"),
                    error=str(exc),
                )
                errors.append(
                    {
                        "question_id": str(question.get("id") or ""),
                        "error": str(exc),
                    }
                )

        return {
            "generated": generated,
            "errors": errors,
        }

    def resolve_direct_llm_config(self) -> dict[str, Any]:
        """Resolve an OpenAI-compatible endpoint for direct explanation generation."""
        env_base_url = (
            os.getenv("EXAM_PAST_EXAM_LLM_BASE_URL")
            or os.getenv("EXAM_LLM_BASE_URL")
            or os.getenv("EXAM_OPENAI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LOCAL_ENDPOINT")
            or ""
        ).strip()
        env_model = (
            os.getenv("EXAM_PAST_EXAM_LLM_MODEL")
            or os.getenv("EXAM_LLM_MODEL")
            or os.getenv("EXAM_CODEX_MODEL")
            or os.getenv("EXAM_OPENAI_MODEL")
            or os.getenv("EXAM_OPENCODE_MODEL")
            or ""
        ).strip()
        env_api_key = (
            os.getenv("EXAM_PAST_EXAM_LLM_API_KEY")
            or os.getenv("EXAM_LLM_API_KEY")
            or os.getenv("EXAM_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        ).strip()
        if env_base_url and env_model:
            model_id = env_model.split("/", 1)[1] if "/" in env_model else env_model
            headers = {}
            openai_org = (
                os.getenv("EXAM_OPENAI_ORGANIZATION")
                or os.getenv("OPENAI_ORGANIZATION")
                or ""
            ).strip()
            openai_project = (os.getenv("EXAM_OPENAI_PROJECT") or os.getenv("OPENAI_PROJECT") or "").strip()
            if openai_org:
                headers["OpenAI-Organization"] = openai_org
            if openai_project:
                headers["OpenAI-Project"] = openai_project
            return {
                "base_url": env_base_url.rstrip("/"),
                "model_id": model_id,
                "api_key": env_api_key,
                "headers": headers,
                "source": "env",
            }

        if not self.opencode_config_path.exists():
            raise RuntimeError("找不到可直接呼叫的 LLM 設定，且 opencode.json 不存在。")

        try:
            config = json.loads(self.opencode_config_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"opencode.json 無法讀取: {exc}") from exc

        model_ref = env_model or str(config.get("model") or "").strip()
        if not model_ref:
            available_models = collect_opencode_available_models(config)
            model_ref = available_models[0] if available_models else ""

        if "/" not in model_ref:
            raise RuntimeError("opencode.json 未設定有效的 provider/model 預設模型。")

        provider_id, model_id = model_ref.split("/", 1)
        provider_config = (config.get("provider") or {}).get(provider_id) or {}
        options = provider_config.get("options") or {}
        base_url = _resolve_variable(str(options.get("baseURL") or options.get("base_url") or ""))
        if not base_url:
            raise RuntimeError(f"provider `{provider_id}` 缺少 options.baseURL，無法直接呼叫。")

        api_key = _resolve_variable(str(options.get("apiKey") or options.get("api_key") or ""))
        headers = {
            str(key): _resolve_variable(str(value))
            for key, value in (options.get("headers") or {}).items()
            if value is not None
        }
        return {
            "base_url": base_url.rstrip("/"),
            "model_id": model_id,
            "api_key": api_key,
            "headers": headers,
            "source": f"opencode:{provider_id}",
        }

    def _invoke_llm(self, prompt: str, *, provider=None) -> str:
        if provider is not None:
            try:
                return provider.run(prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("past_exam_explanation_provider_fallback", error=str(exc))

        llm_config = self.resolve_direct_llm_config()
        return self._call_openai_compatible_completion(prompt, llm_config)

    def _call_openai_compatible_completion(self, prompt: str, llm_config: dict[str, Any]) -> str:
        headers = {
            "Content-Type": "application/json",
            **(llm_config.get("headers") or {}),
        }
        if llm_config.get("api_key"):
            headers["Authorization"] = f"Bearer {llm_config['api_key']}"

        candidates = [
            (
                f"{llm_config['base_url']}/responses",
                {
                    "model": llm_config["model_id"],
                    "input": prompt,
                },
                "responses",
            ),
            (
                f"{llm_config['base_url']}/completions",
                {
                    "model": llm_config["model_id"],
                    "prompt": prompt,
                    "temperature": 0.2,
                    "max_tokens": 1000,
                },
                "completion",
            ),
            (
                f"{llm_config['base_url']}/chat/completions",
                {
                    "model": llm_config["model_id"],
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是麻醉專科考題助教。請只回傳 JSON。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1000,
                },
                "chat",
            ),
        ]

        last_error: Exception | None = None
        for url, payload, mode in candidates:
            req = request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=self.request_timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
            except HTTPError as exc:
                last_error = exc
                continue
            except URLError as exc:
                last_error = exc
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"LLM 回傳非 JSON payload: {raw[:200]}") from exc

            text = self._extract_completion_text(data, mode=mode)
            if text.strip():
                logger.info(
                    "past_exam_explanation_direct_llm_called",
                    endpoint=url,
                    mode=mode,
                    model=llm_config["model_id"],
                    source=llm_config.get("source"),
                )
                return text

        raise RuntimeError(f"直接呼叫 OpenAI-compatible endpoint 失敗: {last_error}")

    @staticmethod
    def _extract_completion_text(payload: dict[str, Any], *, mode: str) -> str:
        if mode == "responses":
            return extract_responses_api_text(payload)

        choices = payload.get("choices") or []
        if not choices:
            return ""

        first_choice = choices[0] or {}
        if mode == "completion":
            return str(first_choice.get("text") or "")

        return extract_chat_completion_text(payload)

    def _extract_explanation(self, raw_text: str) -> str:
        cleaned = re.sub(r"<think>.*?</think>", " ", raw_text or "", flags=re.DOTALL | re.IGNORECASE)
        cleaned = cleaned.strip()

        json_candidates = re.findall(r"```(?:json)?\s*(\{.+?\})\s*```", cleaned, re.DOTALL)
        brace_object = self._extract_balanced_json(cleaned)
        if brace_object:
            json_candidates.append(brace_object)

        for candidate in json_candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                explanation = str(parsed.get("explanation") or parsed.get("詳解") or "").strip()
                if explanation:
                    return explanation

        cleaned = self._strip_reasoning_wrappers(cleaned)
        cleaned = re.sub(r"^\s*(?:explanation|詳解)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _strip_reasoning_wrappers(self, text: str) -> str:
        cleaned = text.strip()

        drafting_markers = [
            "*Drafting content:*",
            "Drafting content:",
            "Drafting content",
            "草稿內容：",
        ]
        for marker in drafting_markers:
            marker_index = cleaned.find(marker)
            if marker_index != -1:
                cleaned = cleaned[marker_index + len(marker) :].strip()
                break

        if "Thinking Process:" in cleaned:
            for lead_marker in ("本題", "此題", "正確答案為", "選項 A", "A.", "A：", "A:"):
                lead_index = cleaned.find(lead_marker)
                if lead_index != -1:
                    cleaned = cleaned[lead_index:].strip()
                    break

        end_patterns = [
            r"\n\s*\d+\.\s+\*\*Review.*$",
            r"\n\s*\d+\.\s+\*\*Count.*$",
            r"\n\s*\d+\.\s+Review.*$",
            r"\n\s*\d+\.\s+Count.*$",
            r"\n\s*\*\*Review.*$",
        ]
        for pattern in end_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

        cleanup_prefix_patterns = [
            r"^\s*Thinking Process:\s*",
            r"^\s*\d+\.\s+\*\*Analyze.*?\n",
            r"^\s*\d+\.\s+\*\*Draft.*?\n",
        ]
        for pattern in cleanup_prefix_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

        return cleaned.strip()

    @staticmethod
    def _extract_balanced_json(text: str) -> str | None:
        start_index = text.find("{")
        if start_index == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False
        for index in range(start_index, len(text)):
            char = text[index]
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start_index : index + 1]
        return None

    @staticmethod
    def _looks_like_textbook_document(title: str, filename: str) -> bool:
        haystack = _normalize_text(f"{title} {filename}")
        if not haystack:
            return False

        if re.fullmatch(r"(doc\s*)?\d+", haystack):
            return False

        excluded_keywords = (
            "筆試",
            "考題",
            "試卷",
            "答案",
            "question",
            "questions",
            "answer key",
            "answerkey",
            "mock exam",
            "past exam",
            "paper test",
            "trial",
        )
        if any(keyword in haystack for keyword in excluded_keywords):
            return False

        textbook_keywords = (
            "miller",
            "anesthesia",
            "anaesthesia",
            "critical care",
            "handbook",
            "manual",
            "chapter",
            "pediatric",
            "neonatal",
        )
        return any(keyword in haystack for keyword in textbook_keywords)

    @staticmethod
    def _normalize_label(value: str) -> str:
        return _normalize_text(value)

    def _question_search_text(self, question: dict) -> str:
        return " ".join(
            [
                str(question.get("question_text") or ""),
                " ".join(question.get("options", []) or []),
                " ".join(question.get("topics", []) or []),
                " ".join(question.get("concept_names", []) or []),
            ]
        )

    def _question_tokens(self, question: dict) -> set[str]:
        return self._text_tokens(self._question_search_text(question))

    @staticmethod
    def _text_tokens(text: str) -> set[str]:
        normalized = _normalize_text(text)
        latin_tokens = re.findall(r"[a-z0-9]{3,}", normalized)
        latin_tokens = {token for token in latin_tokens if token not in MATCH_STOPWORDS}
        cjk_tokens = {match for match in re.findall(r"[\u4e00-\u9fff]{2,}", text)}
        return latin_tokens | cjk_tokens

    @staticmethod
    def _similarity_score(
        *,
        target_tokens: set[str],
        target_topics: set[str],
        target_concepts: set[str],
        target_text: str,
        candidate_tokens: set[str],
        candidate_topics: set[str],
        candidate_concepts: set[str],
        candidate_text: str,
    ) -> float:
        score = 0.0
        if target_tokens and candidate_tokens:
            token_overlap = len(target_tokens & candidate_tokens)
            score += token_overlap / max(len(target_tokens), 1)

        if target_topics and candidate_topics:
            score += 1.2 * len(target_topics & candidate_topics)

        if target_concepts and candidate_concepts:
            score += 1.6 * len(target_concepts & candidate_concepts)

        if target_text and candidate_text:
            if target_text in candidate_text or candidate_text in target_text:
                score += 0.4

        return score


_service: PastExamExplanationService | None = None


def get_past_exam_explanation_service() -> PastExamExplanationService:
    """Return the singleton explanation service used by Streamlit."""
    global _service
    required_attrs = (
        "find_textbook_evidence",
        "safe_find_textbook_evidence",
        "build_question_semantic_outline",
    )
    if _service is None or not all(hasattr(_service, attr) for attr in required_attrs):
        _service = PastExamExplanationService()
    return _service
