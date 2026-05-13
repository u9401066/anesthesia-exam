"""
Streamlit Chat UI - 流式聊天介面

三欄佈局：側邊選單 + 考題操作區 + 常駐 Chat
支援：
- Crush 自動啟動與配置載入
- 真正的流式題目生成與即時預覽
- 題庫管理與作答練習
- 完整的 logging 追蹤
"""

import hashlib
import html
import os
import re
import sys
from collections import Counter
from pathlib import Path

# 確保專案根目錄在 Python path 中
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import json
import random
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any, Optional, cast

import streamlit as st

from src.application.services.past_exam_explanation_service import get_past_exam_explanation_service
from src.application.services.past_exam_figure_service import get_past_exam_figure_service
from src.application.services.textbook_generation_service import get_textbook_generation_service
from src.infrastructure import agent as agent_module
from src.infrastructure.logging import bootstrap_logging, new_run_id
from src.domain.value_objects.answer import (
    question_allows_multiple as _question_type_allows_multiple,
    format_answer_letters as _format_answer_letters,
    normalize_answer_letters as _normalize_answer_letters,
)
from src.presentation.streamlit.chat_panel import (
    build_chat_stream_error_message,
    compute_chat_history_height,
    ensure_chat_stream_job_store,
    is_missing_chat_job_error,
)
from src.presentation.streamlit.document_manifest import normalize_manifest_paths as _normalize_manifest_paths
from src.presentation.streamlit.generation.controller import autosave_generated_questions_to_drafts
from src.presentation.streamlit.generation.fragments import (
    render_question_review_form,
    render_source_info,
)
from src.presentation.streamlit.generation.orchestration import (
    build_generation_prompt,
    create_generation_execution_ui,
    extract_questions_from_response,
    stream_agent_generate,
)
from src.presentation.streamlit.past_exam_fragments import render_past_exam_question_assets

AgentProviderConfig = agent_module.AgentProviderConfig
create_agent_provider = agent_module.create_agent_provider
collect_opencode_available_models = getattr(agent_module, "collect_opencode_available_models", lambda config: [])
resolve_opencode_default_model = getattr(agent_module, "resolve_opencode_default_model", lambda config: None)
collect_openclaw_available_models = getattr(agent_module, "collect_openclaw_available_models", lambda config: [])
resolve_openclaw_default_model = getattr(agent_module, "resolve_openclaw_default_model", lambda config: None)

# 初始化結構化 logging（JSON 寫入 logs/）
LOG_DIR = PROJECT_DIR / "logs"
APP_RUN_ID = new_run_id("web")
logger = bootstrap_logging(
    __name__,
    log_dir=LOG_DIR,
    extra_context={"run_id": APP_RUN_ID, "provider": "streamlit"},
)

# 設定頁面
st.set_page_config(
    page_title="Anesthesia Exam Generator",
    page_icon="🩺",
    layout="wide",
)

# 路徑配置
DATA_DIR = PROJECT_DIR / "data"
QUESTIONS_DIR = DATA_DIR / "questions"
EXAMS_DIR = DATA_DIR / "exams"
UPLOADS_DIR = DATA_DIR / "sources" / "uploads"
ASSET_AWARE_DIR = PROJECT_DIR / "libs" / "asset-aware-mcp"
CRUSH_CONFIG_PATH = PROJECT_DIR / "crush.json"
OPENCODE_CONFIG_PATH = PROJECT_DIR / "opencode.json"
SOURCES_MANIFEST = DATA_DIR / "sources" / "manifest.json"

PROMPT_PRESETS = {
    "標準臨床題": "請優先出臨床情境導向題，干擾選項要合理且常見。",
    "高難鑑別題": "請提高鑑別難度，加入相似機轉藥物或監測陷阱，詳解需指出為何其他選項錯。",
    "教學詳解題": "每題請提供教學式詳解：核心觀念、臨床應用、常見誤解。",
}

SOURCE_MODE_EXISTING = "使用既有已拆解教材"
SOURCE_MODE_UPLOAD = "先上傳新教材再出題"
SOURCE_MODE_TEMPLATE = "直接拿考古題模板改寫"
SOURCE_MODE_OPTIONS = [SOURCE_MODE_EXISTING, SOURCE_MODE_UPLOAD, SOURCE_MODE_TEMPLATE]

WORKBENCH_PAGE = "📝 出題工作台"
LEGACY_GENERATE_PAGE = "📝 生成考題"
LEGACY_DRAFT_PAGE = "🗃️ 草稿箱"

PAGE_OPTIONS = [WORKBENCH_PAGE, "✍️ 作答練習", "📚 題庫管理", "📋 出題需求", "📊 統計"]
PAGE_LABEL_TO_PARAM = {
    WORKBENCH_PAGE: "generate",
    "✍️ 作答練習": "practice",
    "📚 題庫管理": "library",
    "📋 出題需求": "scope",
    "📊 統計": "stats",
}
PAGE_PARAM_TO_LABEL = {value: key for key, value in PAGE_LABEL_TO_PARAM.items()}
PAGE_PARAM_TO_LABEL["drafts"] = "📚 題庫管理"
PAGE_LABEL_ALIASES = {
    LEGACY_GENERATE_PAGE: WORKBENCH_PAGE,
    LEGACY_DRAFT_PAGE: "📚 題庫管理",
}

CHAT_QUICK_PROMPTS = [
    "幫我說明這個頁面的最佳操作順序。",
    "幫我檢查目前選題的詳解品質。",
    "請提供一個題目審閱 checklist。",
]

PRACTICE_SOURCE_GENERAL = "general_bank"
PRACTICE_SOURCE_GENERATED = "generated_preview"
PRACTICE_SOURCE_PAST_EXAM = "past_exam"
SUPPORTED_AGENT_PROVIDERS = ("crush", "opencode", "copilot-sdk", "codex", "openclaw")
MCP_CAPABLE_AGENT_PROVIDERS = ("crush", "opencode")
REQUIRED_REPO_MCP_SERVERS = ("exam-generator", "asset-aware")
PRACTICE_PATTERN_LABELS = {
    "direct_recall": "直接記憶",
    "clinical_scenario": "臨床情境",
    "comparison": "比較題",
    "mechanism": "機轉題",
    "calculation": "計算題",
    "image_based": "圖片題",
    "best_answer": "最佳答案",
    "negation": "否定題",
    "sequence": "順序題",
}


def provider_supports_repo_mcp(provider_name: str, agent_meta: Optional[dict] = None) -> bool:
    """Return whether the configured provider can use the repo MCP workflows."""
    normalized_provider = str(provider_name or "").strip().lower()
    if normalized_provider in MCP_CAPABLE_AGENT_PROVIDERS:
        return True
    if normalized_provider != "openclaw":
        return False

    servers = (agent_meta or {}).get("mcp_servers") or {}
    if not isinstance(servers, dict):
        return False
    configured_servers = {str(name or "").strip() for name in servers.keys() if str(name or "").strip()}
    return set(REQUIRED_REPO_MCP_SERVERS).issubset(configured_servers)


def get_configured_agent_provider_name() -> str:
    """Read the server-controlled agent provider used by the UI."""
    provider_name = str(os.getenv("EXAM_AGENT_PROVIDER", "opencode") or "opencode").strip().lower()
    return provider_name or "opencode"


def get_configured_agent_model(provider_name: str, agent_meta: Optional[dict] = None) -> str:
    """Read the server-controlled model used by the UI."""
    meta = agent_meta or {}

    if provider_name == "opencode":
        return str(os.getenv("EXAM_OPENCODE_MODEL") or meta.get("model") or "").strip()
    if provider_name == "crush":
        return str(os.getenv("EXAM_CRUSH_MODEL") or meta.get("model") or "").strip()
    if provider_name == "copilot-sdk":
        return str(os.getenv("EXAM_COPILOT_SDK_MODEL") or meta.get("model") or "").strip()
    if provider_name == "codex":
        return str(
            os.getenv("EXAM_CODEX_MODEL")
            or os.getenv("EXAM_OPENAI_MODEL")
            or os.getenv("EXAM_AGENT_MODEL")
            or meta.get("model")
            or "gpt-5.3-codex"
        ).strip()
    if provider_name == "openclaw":
        return str(
            os.getenv("EXAM_OPENCLAW_MODEL")
            or os.getenv("EXAM_AGENT_MODEL")
            or meta.get("model")
            or ""
        ).strip()

    return str(os.getenv("EXAM_AGENT_MODEL") or meta.get("model") or "").strip()


def question_formal_save_ready(question: dict) -> bool:
    """Use the singleton service directly to avoid brittle symbol-level imports."""
    return get_textbook_generation_service().question_formal_save_ready(question)


def _empty_textbook_evidence_pack(reason: str) -> dict[str, Any]:
    return {
        "source_ready": False,
        "matched_doc_id": None,
        "matched_doc_title": None,
        "gate_reasons": [reason] if reason else [],
        "source": {},
    }


def _normalize_textbook_evidence_pack(evidence_pack: Any) -> dict[str, Any]:
    if isinstance(evidence_pack, tuple):
        for item in evidence_pack:
            if isinstance(item, dict):
                evidence_pack = item
                break

    if not isinstance(evidence_pack, dict):
        return _empty_textbook_evidence_pack("教材證據格式不支援")

    normalized = _empty_textbook_evidence_pack("")
    normalized.update({key: value for key, value in evidence_pack.items() if key != "source"})
    normalized["source"] = dict(evidence_pack.get("source") or {}) if isinstance(evidence_pack.get("source"), dict) else {}
    normalized["source_ready"] = bool(normalized.get("source_ready"))

    gate_reasons = normalized.get("gate_reasons")
    if isinstance(gate_reasons, list):
        normalized["gate_reasons"] = [str(reason) for reason in gate_reasons if str(reason).strip()]
    elif gate_reasons:
        normalized["gate_reasons"] = [str(gate_reasons)]
    else:
        normalized["gate_reasons"] = []

    return normalized


def _resolve_textbook_evidence(explanation_service, question: dict) -> dict[str, Any]:
    lookup = getattr(explanation_service, "safe_find_textbook_evidence", None)
    if not callable(lookup):
        lookup = getattr(explanation_service, "find_textbook_evidence", None)

    if callable(lookup):
        try:
            return _normalize_textbook_evidence_pack(lookup(question))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "streamlit_textbook_evidence_lookup_failed",
                question_id=question.get("id"),
                error=str(exc),
            )

    textbook_generation_service = getattr(explanation_service, "textbook_generation_service", None)
    catalog_lookup = getattr(explanation_service, "list_textbook_doc_catalog", None)
    build_lookup = getattr(textbook_generation_service, "build_evidence_pack_for_question", None)

    if callable(catalog_lookup) and callable(build_lookup):
        try:
            doc_catalog = catalog_lookup()
            candidate_doc_ids = [
                str(doc.get("doc_id") or "").strip()
                for doc in doc_catalog
                if isinstance(doc, dict) and str(doc.get("doc_id") or "").strip()
            ]
            if candidate_doc_ids:
                return _normalize_textbook_evidence_pack(
                    build_lookup(
                        question,
                        selected_doc_ids=candidate_doc_ids,
                        selected_sections=None,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "streamlit_textbook_evidence_fallback_failed",
                question_id=question.get("id"),
                error=str(exc),
            )

    return _empty_textbook_evidence_pack("目前無法解析教材證據")


def _truncate_text(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 0)].rstrip() + "..."


def sync_current_page_from_nav() -> None:
    """Keep page navigation state in one place when the sidebar radio changes."""
    selected_page = PAGE_LABEL_ALIASES.get(st.session_state.get("page_nav"), st.session_state.get("page_nav"))
    if selected_page in PAGE_OPTIONS:
        st.session_state.current_page = selected_page
        sync_query_params_with_page(selected_page)


def navigate_to(page: str) -> None:
    """Queue a page switch so the next rerun applies it before widgets render."""
    page = PAGE_LABEL_ALIASES.get(page, page)
    if page not in PAGE_OPTIONS:
        return
    st.session_state.current_page = page
    st.session_state.pending_page_navigation = page


def navigate_to_without_query_sync(page: str) -> None:
    """Switch pages on the next rerun without forcing an immediate URL-param update."""
    page = PAGE_LABEL_ALIASES.get(page, page)
    if page not in PAGE_OPTIONS:
        return
    st.session_state.current_page = page
    st.session_state.pending_page_navigation = page
    st.session_state.skip_query_param_sync_once = True


def sync_nav_widget_state() -> None:
    """Ensure the sidebar radio reflects the current programmatic page state."""
    current_page = PAGE_LABEL_ALIASES.get(st.session_state.get("current_page"), st.session_state.get("current_page"))
    if current_page in PAGE_OPTIONS and st.session_state.get("page_nav") != current_page:
        st.session_state.page_nav = current_page


def get_page_from_query_params() -> str:
    """Restore the selected page after a browser refresh by reading URL params."""
    page_param = st.query_params.get("page")
    if isinstance(page_param, list):
        page_param = page_param[0] if page_param else None
    if not page_param:
        return PAGE_OPTIONS[0]
    return PAGE_PARAM_TO_LABEL.get(page_param, PAGE_OPTIONS[0])


def sync_query_params_with_page(page: str) -> None:
    """Persist the active page in the URL so refresh keeps the current view."""
    page_param = PAGE_LABEL_TO_PARAM.get(page)
    if not page_param:
        return

    current_param = st.query_params.get("page")
    if isinstance(current_param, list):
        current_param = current_param[0] if current_param else None
    if current_param != page_param:
        st.query_params["page"] = page_param


def set_draft_flash(message: str, level: str = "success") -> None:
    """Store a draft-box flash message that can survive a rerun."""
    st.session_state.draft_flash = message
    st.session_state.draft_flash_level = level


def render_draft_flash() -> None:
    """Render and clear the current draft flash message."""
    message = str(st.session_state.get("draft_flash", "") or "").strip()
    if not message:
        return

    level = str(st.session_state.get("draft_flash_level", "success") or "success")
    if hasattr(st, "toast") and level in {"success", "info"}:
        st.toast(message, icon="✅" if level == "success" else "ℹ️")
    else:
        flash_renderers = {
            "success": st.success,
            "warning": st.warning,
            "error": st.error,
            "info": st.info,
        }
        flash_renderers.get(level, st.info)(message)
    st.session_state.draft_flash = ""
    st.session_state.draft_flash_level = "success"


def is_e2e_test_mode() -> bool:
    """Expose small UI anchors only for browser smoke tests."""
    return os.getenv("ANESTHESIA_EXAM_E2E_TEST_MODE") == "1"


def _build_e2e_source_location(page: int, line_start: int, line_end: int, original_text: str) -> dict:
    """Build deterministic source-location payloads for E2E browser tests."""
    return {
        "page": page,
        "line_start": line_start,
        "line_end": line_end,
        "bbox": [72, 144, 420, 182],
        "original_text": original_text,
    }


def build_e2e_textbook_review_questions(mode: str) -> list[dict]:
    """Provide deterministic textbook review payloads for browser smoke tests."""
    base_source = {
        "document": "Miller E2E Textbook",
        "chapter": "ACUTE CIRCULATORY FAILURE IN CHILDREN (SHOCK AND SEPSIS)",
        "section": "Therapy and Outcomes",
    }

    if mode == "preview":
        preview_question = {
            "id": "e2e-textbook-preview-question",
            "question_text": "E2E textbook preview-only shock question",
            "options": [
                "Restore perfusion before definitive etiologic therapy",
                "Delay resuscitation until central access is available",
                "Avoid reassessment after initial fluid administration",
                "Treat only laboratory abnormalities",
            ],
            "correct_answer": "A",
            "explanation": "Preview-only draft used to verify textbook review gating in Streamlit.",
            "difficulty": "medium",
            "topics": ["shock", "textbook-e2e"],
            "source": dict(base_source),
            "preview_only": True,
            "formal_save_ready": False,
            "generation_mode": "preview_only",
            "evidence_pack": {
                "source_ready": False,
                "matched_doc_id": "doc_e2e_preview",
                "matched_doc_title": "Miller E2E Textbook",
                "context_sections": ["Therapy and Outcomes"],
                "gate_reasons": [
                    "preview-only 模式只使用 section/chapter/full text 上下文，不可直接正式入庫。"
                ],
            },
        }
        return [preview_question]

    if mode == "formal":
        source = {
            **base_source,
            "stem_source": _build_e2e_source_location(
                6,
                136,
                137,
                "The overall goal of therapy in shock is to restore oxygen delivery to tissues and treat the underlying cause.",
            ),
            "answer_source": _build_e2e_source_location(
                6,
                130,
                131,
                "Rapid perfusion recovery is required while the team identifies and treats the etiology of shock.",
            ),
            "explanation_sources": [
                _build_e2e_source_location(
                    6,
                    138,
                    140,
                    "Therapy and outcomes are linked to frequent reassessment of perfusion, oxygen delivery, and response to interventions.",
                )
            ],
        }
        formal_question = {
            "id": "e2e-textbook-formal-question",
            "question_text": "E2E textbook formal-save shock question",
            "options": [
                "Restore oxygen delivery to tissues while treating the cause",
                "Wait for CT imaging before any resuscitation",
                "Use only maintenance fluids and avoid vasoactive support",
                "Ignore perfusion endpoints once blood pressure normalizes",
            ],
            "correct_answer": "A",
            "explanation": "Formal-save-ready draft used to verify textbook evidence-pack persistence in Streamlit.",
            "difficulty": "medium",
            "topics": ["shock", "textbook-e2e"],
            "source": source,
            "preview_only": False,
            "formal_save_ready": True,
            "generation_mode": "formal",
            "evidence_pack": {
                "source_ready": True,
                "matched_doc_id": "doc_e2e_formal",
                "matched_doc_title": "Miller E2E Textbook",
                "gate_reasons": [],
                "source": source,
            },
        }
        return [formal_question]

    raise ValueError(f"Unsupported E2E textbook mode: {mode}")


def schedule_draft_batch_selection_reset() -> None:
    """Reset batch-selection state on the next rerun before widgets mount."""
    st.session_state.draft_batch_selection_reset_pending = True
    st.session_state.draft_batch_selection_override = []


def get_practice_question_key(question: dict, fallback_index: int) -> str:
    """Return a stable key for practice widgets and answer mapping."""
    question_id = str(question.get("id") or "").strip()
    if question_id:
        return question_id

    existing_widget_key = str(question.get("_practice_widget_key") or question.get("_review_widget_key") or "").strip()
    if existing_widget_key:
        question["_practice_widget_key"] = existing_widget_key
        return existing_widget_key

    key_seed = "|".join(
        [
            question.get("question_text", ""),
            json.dumps(question.get("options", []), ensure_ascii=False),
            str(fallback_index),
        ]
    )
    widget_key = hashlib.sha1(key_seed.encode("utf-8")).hexdigest()[:12]
    question["_practice_widget_key"] = widget_key
    return widget_key


def format_past_exam_catalog_label(exam: dict) -> str:
    """Format a readable label for a past-exam catalog entry."""
    exam_year = exam.get("exam_year", "-")
    exam_name = exam.get("exam_name", "未命名考卷")
    total_questions = exam.get("total_questions", 0)
    return f"{exam_year} 年 {exam_name} ({total_questions} 題)"


def _clear_practice_answer_widget_state(questions: list[dict]) -> None:
    """Clear radio widget state so new practice sessions never reuse stale answers."""
    for index, question in enumerate(questions):
        question_key = get_practice_question_key(question, index)
        widget_key = f"q_{question_key}"
        if widget_key in st.session_state:
            del st.session_state[widget_key]


def _build_option_label(index: int, option: object) -> str:
    """Build a stable visible option label, preserving already-prefixed options."""
    prefix = chr(65 + index)
    option_text = str(option or "").strip()
    if not option_text:
        return f"{prefix}. "

    if re.match(rf"^{re.escape(prefix)}[\)\.:：、\s]", option_text):
        return option_text
    return f"{prefix}. {option_text}"


def _letters_to_option_labels(letters: tuple[str, ...], option_labels: list[str]) -> list[str]:
    labels: list[str] = []
    for letter in letters:
        idx = ord(letter) - 65
        if 0 <= idx < len(option_labels):
            labels.append(option_labels[idx])
    return labels


def _letters_from_option_labels(selected_labels: list[str]) -> tuple[str, ...]:
    letters: set[str] = set()
    for label in selected_labels:
        match = re.match(r"^\s*([A-Z])", str(label or "").strip().upper())
        if match and "A" <= match.group(1) <= "Z":
            letters.add(match.group(1))
    return tuple(sorted(letters))


def start_practice_session(questions: list[dict], context: Optional[dict] = None) -> None:
    """Start a fresh practice round with cleared widget state and context metadata."""
    previous_questions = list(st.session_state.get("practice_questions", []))
    next_questions = list(questions)

    _clear_practice_answer_widget_state(previous_questions)
    _clear_practice_answer_widget_state(next_questions)

    st.session_state.practice_questions = next_questions
    st.session_state.practice_answers = {}
    st.session_state.practice_submitted = False
    st.session_state.show_explanations = {}
    st.session_state.practice_context = dict(context or {})


def queue_practice_session(questions: list[dict], context: Optional[dict] = None) -> None:
    """Defer practice-session setup to the next rerun before widgets are rebuilt."""
    st.session_state.pending_practice_questions = list(questions)
    st.session_state.pending_practice_context = dict(context or {})
    navigate_to("✍️ 作答練習")


def clear_practice_session(clear_questions: bool = True) -> None:
    """Reset the current practice round and optionally clear the question set."""
    current_questions = list(st.session_state.get("practice_questions", []))
    _clear_practice_answer_widget_state(current_questions)

    if clear_questions:
        st.session_state.practice_questions = []

    st.session_state.practice_answers = {}
    st.session_state.practice_submitted = False
    st.session_state.show_explanations = {}
    st.session_state.practice_context = {}


def summarize_practice_results(questions: list[dict], practice_answers: dict[str, str]) -> dict:
    """Build a normalized result summary for practice results and review UIs."""
    result_rows: list[dict] = []
    correct_count = 0
    answered_count = 0

    for index, question in enumerate(questions):
        question_key = get_practice_question_key(question, index)
        option_count = len(question.get("options") or [])
        user_answer = str(practice_answers.get(question_key, "") or "")
        user_letters = _normalize_answer_letters(user_answer, option_count=option_count)
        correct_letters = _normalize_answer_letters(question.get("correct_answer", ""), option_count=option_count)
        is_answered = bool(user_letters)
        is_correct = is_answered and user_letters == correct_letters

        if is_answered:
            answered_count += 1
        if is_correct:
            correct_count += 1

        exam_year = question.get("exam_year")
        exam_name = str(question.get("exam_name", "") or "")
        exam_label = f"{exam_year} 年 {exam_name}" if exam_year or exam_name else "未標記考卷"
        pattern_value = str(question.get("pattern", "") or "")

        result_rows.append(
            {
                "question_text": question.get("question_text", ""),
                "exam_year": exam_year if exam_year not in (None, "") else "未標記",
                "exam_label": exam_label,
                "question_number": question.get("question_number") or index + 1,
                "pattern_label": PRACTICE_PATTERN_LABELS.get(pattern_value, "未分類"),
                "topics": question.get("topics", []),
                "difficulty": question.get("difficulty", "medium"),
                "user_answer": _format_answer_letters(user_letters) or "-",
                "correct_answer": _format_answer_letters(correct_letters) or "-",
                "is_answered": is_answered,
                "is_correct": is_correct,
                "explanation": question.get("explanation", ""),
                "source_page": question.get("source_page"),
                "figure_assets": question.get("figure_assets", []),
                "option_figure_assets": question.get("option_figure_assets", []),
                "source_page_image_path": question.get("source_page_image_path"),
                "image_asset_status": question.get("image_asset_status"),
                "image_asset_note": question.get("image_asset_note"),
            }
        )

    total_questions = len(questions)
    incorrect_count = answered_count - correct_count
    unanswered_count = total_questions - answered_count
    score = (correct_count / total_questions * 100) if total_questions else 0.0
    answered_accuracy = (correct_count / answered_count * 100) if answered_count else 0.0
    review_rows = [row for row in result_rows if not row["is_correct"]]

    return {
        "result_rows": result_rows,
        "review_rows": review_rows,
        "correct_count": correct_count,
        "answered_count": answered_count,
        "incorrect_count": incorrect_count,
        "unanswered_count": unanswered_count,
        "total_questions": total_questions,
        "score": score,
        "answered_accuracy": answered_accuracy,
    }


def build_practice_download_markdown(
    questions: list[dict],
    practice_answers: dict[str, str],
    practice_context: Optional[dict] = None,
    practice_result: Optional[dict] = None,
) -> str:
    """Build a markdown export for the current practice set without persisting it."""
    context = practice_context or {}
    source_label = str(context.get("label") or "未標記來源")
    exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# 練習考卷匯出",
        "",
        f"- 匯出時間：{exported_at}",
        f"- 來源：{source_label}",
        f"- 題數：{len(questions)}",
    ]

    if practice_result is not None:
        lines.extend(
            [
                f"- 作答題數：{practice_result['answered_count']}/{practice_result['total_questions']}",
                f"- 成績：{practice_result['correct_count']}/{practice_result['total_questions']} ({practice_result['score']:.1f}%)",
            ]
        )

    lines.append("")

    for index, question in enumerate(questions, start=1):
        question_key = get_practice_question_key(question, index - 1)
        option_count = len(question.get("options") or [])
        user_answer = str(practice_answers.get(question_key, "") or "")
        user_letters = _normalize_answer_letters(user_answer, option_count=option_count)
        correct_letters = _normalize_answer_letters(question.get("correct_answer", ""), option_count=option_count)
        exam_year = question.get("exam_year")
        exam_name = str(question.get("exam_name", "") or "")
        exam_label = f"{exam_year} 年 {exam_name}".strip() if exam_year or exam_name else "未標記考卷"
        source_page = question.get("source_page")

        lines.extend(
            [
                f"## 第 {index} 題",
                "",
                question.get("question_text", ""),
                "",
                f"- 來源考卷：{exam_label}",
                f"- 題號：{question.get('question_number') or index}",
                f"- 你的答案：{_format_answer_letters(user_letters) or '-'}",
                f"- 正確答案：{_format_answer_letters(correct_letters) or '-'}",
                f"- 難度：{question.get('difficulty', 'medium')}",
            ]
        )

        topics = [str(topic).strip() for topic in question.get("topics", []) if str(topic).strip()]
        if topics:
            lines.append(f"- 主題：{', '.join(topics)}")
        if source_page:
            lines.append(f"- 來源頁碼：p.{source_page}")
        if question.get("source_page_image_path"):
            lines.append(f"- 原題頁面預覽：{question['source_page_image_path']}")

        lines.append("")
        lines.append("### 選項")
        lines.append("")
        for option_index, option in enumerate(question.get("options", [])):
            lines.append(f"- {chr(65 + option_index)}. {option}")

        option_figure_assets = question.get("option_figure_assets", []) or []
        if option_figure_assets:
            lines.extend(["", "### 圖像選項", ""])
            for asset in option_figure_assets:
                lines.append(f"- {asset.get('label', '?')}: {asset.get('path', '')}")

        figure_assets = question.get("figure_assets", []) or []
        if figure_assets:
            lines.extend(["", "### 題目相關圖像", ""])
            for asset in figure_assets:
                lines.append(f"- {asset.get('caption') or asset.get('id')}: {asset.get('path', '')}")

        explanation = str(question.get("explanation", "") or "").strip()
        if explanation:
            lines.extend(["", "### 詳解", "", explanation])

        lines.extend(["", "---", ""])

    return "\n".join(lines).strip() + "\n"


def build_practice_download_filename(practice_context: Optional[dict] = None) -> str:
    """Build a readable filename for the current practice export."""
    context = practice_context or {}
    source_label = str(context.get("label") or "practice").strip().lower()
    safe_label = re.sub(r"[^a-z0-9_-]+", "-", source_label).strip("-") or "practice"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_label}_{timestamp}.md"


def build_practice_breakdown_rows(
    result_rows: list[dict],
    group_key: str,
    label: str,
    numeric_sort_desc: bool = False,
) -> list[dict]:
    """Aggregate practice results into a dataframe-friendly breakdown table."""
    grouped: dict[str, dict] = {}

    for row in result_rows:
        raw_value = row.get(group_key)
        group_label = raw_value if raw_value not in (None, "", []) else "未標記"
        group_key_str = str(group_label)

        if group_key_str not in grouped:
            grouped[group_key_str] = {
                "_sort_value": raw_value,
                "題數": 0,
                "答對": 0,
                "答錯": 0,
                "未作答": 0,
            }

        grouped[group_key_str]["題數"] += 1
        if row.get("is_correct"):
            grouped[group_key_str]["答對"] += 1
        elif row.get("is_answered"):
            grouped[group_key_str]["答錯"] += 1
        else:
            grouped[group_key_str]["未作答"] += 1

    table_rows: list[dict] = []
    for group_label, counts in grouped.items():
        total = counts["題數"]
        accuracy = (counts["答對"] / total * 100) if total else 0.0
        table_rows.append(
            {
                label: group_label,
                "題數": total,
                "答對": counts["答對"],
                "答錯": counts["答錯"],
                "未作答": counts["未作答"],
                "正確率": f"{accuracy:.1f}%",
                "_sort_value": counts["_sort_value"],
            }
        )

    if numeric_sort_desc:
        table_rows.sort(
            key=lambda item: item["_sort_value"] if isinstance(item["_sort_value"], (int, float)) else -1,
            reverse=True,
        )
    else:
        table_rows.sort(key=lambda item: str(item[label]))

    for row in table_rows:
        row.pop("_sort_value", None)

    return table_rows


def build_practice_weak_topic_rows(result_rows: list[dict]) -> list[dict]:
    """Summarize wrong or unanswered questions by topic for quick review."""
    weak_topics: Counter[str] = Counter()

    for row in result_rows:
        if row.get("is_correct"):
            continue

        topics = [str(topic).strip() for topic in row.get("topics", []) if str(topic).strip()]
        if not topics:
            topics = ["未標記主題"]

        for topic in topics:
            weak_topics[topic] += 1

    return [{"主題": topic, "錯題/未作答": count} for topic, count in weak_topics.most_common(8)]


def inject_app_styles() -> None:
    """注入全域樣式，讓介面具有一致的視覺語言。"""
    st.markdown(
        """
        <style>
            :root {
                --bg: #f6f2e8;
                --bg-soft: rgba(255, 252, 246, 0.82);
                --surface: rgba(255, 255, 255, 0.78);
                --surface-strong: rgba(255, 255, 255, 0.92);
                --line: rgba(18, 82, 76, 0.12);
                --text: #163532;
                --muted: #5f7b76;
                --accent: #0f766e;
                --accent-soft: rgba(15, 118, 110, 0.12);
                --warm: #d97706;
                --shadow: 0 18px 42px rgba(22, 53, 50, 0.10);
                --radius: 22px;
            }

            html, body, [data-testid="stAppViewContainer"], .stApp {
                color-scheme: light !important;
            }

            body {
                color: var(--text);
                background: #fcfaf5;
            }

            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(15, 118, 110, 0.10), transparent 28%),
                    radial-gradient(circle at top right, rgba(217, 119, 6, 0.10), transparent 22%),
                    linear-gradient(180deg, #fcfaf5 0%, var(--bg) 100%);
                color: var(--text);
            }

            [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
                background: transparent !important;
            }

            [data-testid="stToolbar"] {
                display: none;
            }

            .block-container {
                padding-top: 1.4rem;
                padding-bottom: 2rem;
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(241, 245, 249, 0.95) 0%, rgba(249, 250, 251, 0.92) 100%);
                border-right: 1px solid rgba(15, 118, 110, 0.10);
            }

            [data-testid="stSidebar"],
            [data-testid="stSidebar"] * {
                color: var(--text) !important;
            }

            [data-testid="stSidebar"] .block-container {
                padding-top: 1.8rem;
            }

            [data-testid="stMarkdownContainer"],
            [data-testid="stMarkdownContainer"] p,
            [data-testid="stMarkdownContainer"] li,
            label,
            .stRadio p,
            .stCheckbox p,
            .stSelectbox label,
            .stMultiSelect label,
            .stTextInput label,
            .stNumberInput label,
            .stTextArea label,
            .stFileUploader label,
            .stSlider label {
                color: var(--text) !important;
            }

            [data-baseweb="input"] input,
            [data-baseweb="base-input"],
            .stTextInput input,
            .stTextArea textarea,
            .stNumberInput input,
            .stSelectbox [data-baseweb="select"] > div,
            .stMultiSelect [data-baseweb="select"] > div,
            .stFileUploader [data-testid="stFileUploaderDropzone"] {
                background: rgba(255, 255, 255, 0.92) !important;
                color: var(--text) !important;
                border: 1px solid rgba(18, 82, 76, 0.14) !important;
            }

            [data-baseweb="input"] input::placeholder,
            .stTextInput input::placeholder,
            .stTextArea textarea::placeholder {
                color: var(--muted) !important;
                opacity: 1;
            }

            .stButton > button,
            .stDownloadButton > button,
            .stFileUploader button {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(247, 250, 249, 0.96) 100%) !important;
                color: var(--text) !important;
                border: 1px solid rgba(18, 82, 76, 0.16) !important;
                box-shadow: 0 8px 20px rgba(22, 53, 50, 0.08);
            }

            .stButton > button p,
            .stDownloadButton > button p,
            .stFileUploader button p,
            .stButton > button span,
            .stDownloadButton > button span,
            .stFileUploader button span {
                color: inherit !important;
            }

            .stButton > button:hover,
            .stDownloadButton > button:hover,
            .stFileUploader button:hover {
                background: rgba(15, 118, 110, 0.10) !important;
                color: var(--accent) !important;
                border-color: rgba(15, 118, 110, 0.22) !important;
            }

            [data-testid="stExpander"] summary {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(247, 250, 249, 0.96) 100%) !important;
                color: var(--text) !important;
                border: 1px solid rgba(18, 82, 76, 0.14) !important;
                border-radius: 16px !important;
                box-shadow: 0 8px 20px rgba(22, 53, 50, 0.06);
            }

            [data-testid="stExpander"] summary:hover {
                background: rgba(15, 118, 110, 0.08) !important;
                color: var(--accent) !important;
                border-color: rgba(15, 118, 110, 0.20) !important;
            }

            [data-testid="stExpander"] summary p,
            [data-testid="stExpander"] summary span,
            [data-testid="stExpander"] summary svg {
                color: inherit !important;
                fill: currentColor !important;
            }

            .stNumberInput button {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(247, 250, 249, 0.96) 100%) !important;
                color: var(--text) !important;
                border: 1px solid rgba(18, 82, 76, 0.16) !important;
            }

            .stNumberInput button:hover {
                background: rgba(15, 118, 110, 0.10) !important;
                color: var(--accent) !important;
                border-color: rgba(15, 118, 110, 0.22) !important;
            }

            .stNumberInput button svg,
            .stNumberInput button span {
                color: inherit !important;
                fill: currentColor !important;
            }

            div[data-testid="stVerticalBlockBorderWrapper"] {
                border: 1px solid var(--line);
                border-radius: var(--radius);
                background: var(--surface);
                box-shadow: var(--shadow);
            }

            h1, h2, h3 {
                color: var(--text);
                letter-spacing: -0.02em;
            }

            .app-hero {
                position: relative;
                overflow: hidden;
                padding: 1.5rem 1.6rem;
                border: 1px solid var(--line);
                border-radius: 28px;
                background:
                    linear-gradient(135deg, rgba(255,255,255,0.90) 0%, rgba(244, 251, 250, 0.92) 58%, rgba(255, 248, 238, 0.88) 100%);
                box-shadow: var(--shadow);
                margin-bottom: 1rem;
            }

            .app-hero::after {
                content: "";
                position: absolute;
                right: -20px;
                top: -30px;
                width: 180px;
                height: 180px;
                border-radius: 999px;
                background: radial-gradient(circle, rgba(15,118,110,0.15), transparent 68%);
            }

            .eyebrow {
                font-size: 0.78rem;
                font-weight: 700;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: var(--accent);
                margin-bottom: 0.55rem;
            }

            .app-hero h2 {
                margin: 0;
                font-size: 2.15rem;
                line-height: 1.05;
            }

            .app-hero p {
                margin: 0.65rem 0 0;
                max-width: 46rem;
                font-size: 1rem;
                color: var(--muted);
                line-height: 1.6;
            }

            .hero-pills {
                display: flex;
                flex-wrap: wrap;
                gap: 0.55rem;
                margin-top: 1rem;
            }

            .hero-pill {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.42rem 0.78rem;
                border-radius: 999px;
                background: var(--surface-strong);
                border: 1px solid rgba(15, 118, 110, 0.14);
                font-size: 0.82rem;
                color: var(--text);
            }

            .section-note {
                padding: 0.9rem 1rem;
                border-radius: 16px;
                background: rgba(15, 118, 110, 0.08);
                border: 1px solid rgba(15, 118, 110, 0.10);
                color: var(--text);
                margin: 0.25rem 0 0.75rem;
            }

            .empty-state {
                padding: 1.1rem 1.2rem;
                border-radius: 18px;
                border: 1px dashed rgba(15, 118, 110, 0.24);
                background: rgba(255, 255, 255, 0.55);
                color: var(--muted);
            }

            .empty-state strong {
                display: block;
                color: var(--text);
                margin-bottom: 0.35rem;
            }

            .status-chip-good,
            .status-chip-warn {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.28rem 0.62rem;
                border-radius: 999px;
                font-size: 0.76rem;
                font-weight: 700;
            }

            .status-chip-good {
                background: rgba(22, 163, 74, 0.12);
                color: #166534;
            }

            .status-chip-warn {
                background: rgba(217, 119, 6, 0.12);
                color: #92400e;
            }

            .stChatMessage {
                background: rgba(255, 255, 255, 0.78);
                border: 1px solid rgba(15, 118, 110, 0.08);
                border-radius: 18px;
            }

            [data-testid="stChatInput"] {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(248, 250, 249, 0.92) 100%);
                border: 1px solid rgba(18, 82, 76, 0.14);
                border-radius: 22px;
                box-shadow: 0 12px 26px rgba(22, 53, 50, 0.10);
                padding: 0.45rem 0.55rem;
            }

            [data-testid="stChatInput"] > div {
                background: transparent !important;
            }

            [data-testid="stChatInput"] textarea {
                background: transparent !important;
                color: var(--text) !important;
                border: none !important;
                box-shadow: none !important;
            }

            [data-testid="stChatInput"] textarea::placeholder {
                color: var(--muted) !important;
                opacity: 1;
            }

            [data-testid="stChatInput"] button {
                background: linear-gradient(180deg, #ff6b63 0%, #ff4d4f 100%) !important;
                color: #fff !important;
                border: none !important;
                box-shadow: none !important;
            }

            [data-testid="stChatInput"] button:hover {
                background: linear-gradient(180deg, #f25c54 0%, #e64546 100%) !important;
                color: #fff !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_hero(title: str, subtitle: str, pills: list[str] | None = None) -> None:
    """渲染頁面 Hero 區塊。"""
    pills_markup = ""
    if pills:
        pill_nodes = "".join(f'<span class="hero-pill">{html.escape(pill)}</span>' for pill in pills if pill)
        pills_markup = f'<div class="hero-pills">{pill_nodes}</div>'

    st.markdown(
        f"""
        <section class="app-hero">
            <div class="eyebrow">Anesthesia Exam Workspace</div>
            <h2>{html.escape(title)}</h2>
            <p>{html.escape(subtitle)}</p>
            {pills_markup}
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(title: str, body: str) -> None:
    """渲染簡潔空狀態。"""
    st.markdown(
        f"""
        <div class="empty-state">
            <strong>{html.escape(title)}</strong>
            <span>{html.escape(body)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _resolve_doc_root(manifest: dict) -> Path | None:
    """從 manifest 推回對應的 doc_* 目錄。"""
    explicit_paths = [manifest.get("manifest_path"), manifest.get("markdown_path")]
    for path_str in explicit_paths:
        if not path_str:
            continue
        path = Path(path_str)
        if path.exists():
            return path.parent

    doc_id = manifest.get("doc_id")
    if doc_id:
        candidate = DATA_DIR / doc_id
        if candidate.exists():
            return candidate

    return None


def enrich_doc_manifest(manifest: dict) -> dict:
    """補齊 UI 需要的文件狀態欄位。"""
    from src.application.services.textbook_generation_service import get_textbook_generation_service

    enriched = dict(manifest)
    doc_root = _resolve_doc_root(enriched)
    page_count = enriched.get("page_count") or enriched.get("pages") or enriched.get("page_total") or 0
    doc_id = str(enriched.get("doc_id") or "").strip()
    readiness = (
        get_textbook_generation_service().assess_document_source_readiness(doc_id)
        if doc_id
        else {"source_ready": False, "gate_reasons": ["缺少 doc_id"]}
    )
    has_precise_sources = bool(readiness.get("source_ready"))
    has_markdown = bool(doc_root and (doc_root / "content.md").exists()) or bool(
        doc_root and list(doc_root.glob("*_full.md"))
    )

    enriched["doc_root"] = str(doc_root) if doc_root else ""
    enriched["page_count"] = page_count or "?"
    enriched["has_precise_sources"] = has_precise_sources
    enriched["has_markdown"] = has_markdown
    enriched["source_readiness"] = readiness
    enriched["source_mode_label"] = "精確來源" if has_precise_sources else "全文模式"
    return enriched


def source_page_number(source: dict | None) -> str:
    """從 source 結構取出最合理的頁碼顯示。"""
    if not source:
        return "?"
    stem_source = source.get("stem_source") if isinstance(source, dict) else None
    if isinstance(stem_source, dict) and stem_source.get("page"):
        return str(stem_source["page"])
    if source.get("page"):
        return str(source["page"])
    return "?"


def question_has_precise_source(question: dict) -> bool:
    """判斷題目是否帶有可追溯的精確來源。"""
    source = question.get("source") or {}
    stem_source = source.get("stem_source") or {}
    return bool(source.get("document") and stem_source.get("page") and stem_source.get("original_text"))


def render_selected_docs_summary(selected_docs_info: list[dict]) -> tuple[int, int]:
    """顯示已選教材摘要與 source readiness 狀態。"""
    if not selected_docs_info:
        return 0, 0

    st.markdown("##### 已選教材摘要")
    columns = st.columns(min(3, len(selected_docs_info)))
    precise_ready = 0

    for idx, doc_info in enumerate(selected_docs_info[:3]):
        if doc_info.get("has_precise_sources"):
            precise_ready += 1
        with columns[idx]:
            with st.container(border=True):
                status_class = "status-chip-good" if doc_info.get("has_precise_sources") else "status-chip-warn"
                status_text = "可精確追來源" if doc_info.get("has_precise_sources") else "僅全文模式"
                st.markdown(f'<span class="{status_class}">{status_text}</span>', unsafe_allow_html=True)
                st.markdown(f"**{doc_info.get('title', '未知教材')}**")
                st.caption(f"{doc_info.get('page_count', '?')} 頁 · {doc_info.get('doc_id', '')[:12]}")

    if len(selected_docs_info) > 3:
        st.caption(f"另有 {len(selected_docs_info) - 3} 份教材已選取。")

    missing_precise = len(selected_docs_info) - precise_ready
    return precise_ready, missing_precise


inject_app_styles()


@st.cache_data(ttl=120, show_spinner=False)
def load_indexed_documents() -> list[dict]:
    """載入已索引的文件列表（掃描 data/doc_* manifest + 全域 manifest.json）"""
    docs: list[dict] = []
    seen_ids: set[str] = set()

    # 1) 掃描 data/ 下的 doc_* 目錄 manifest
    if DATA_DIR.exists():
        for doc_dir in sorted(DATA_DIR.iterdir()):
            if not doc_dir.is_dir() or not doc_dir.name.startswith("doc_"):
                continue
            manifest_files = list(doc_dir.glob("*_manifest.json"))
            if not manifest_files:
                continue
            try:
                with open(manifest_files[0], "r", encoding="utf-8") as f:
                    raw_manifest = _normalize_manifest_paths(json.load(f))
                if not isinstance(raw_manifest, dict):
                    raise ValueError("教材 manifest 內容格式錯誤")
                m = raw_manifest
                doc_id = m.get("doc_id", doc_dir.name)
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    docs.append(enrich_doc_manifest(m))
            except Exception as e:
                logger.warning("doc_manifest_load_error", path=str(manifest_files[0]), error=str(e))

    # 2) 補充全域 manifest.json（向後相容）
    if SOURCES_MANIFEST.exists():
        try:
            with open(SOURCES_MANIFEST, "r", encoding="utf-8") as f:
                raw_global_manifest = _normalize_manifest_paths(json.load(f))
            if not isinstance(raw_global_manifest, dict):
                raise ValueError("全域來源 manifest 內容格式錯誤")
            global_manifest = raw_global_manifest
            for src in global_manifest.get("sources", []):
                doc_id = src.get("doc_id", "")
                if doc_id and doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    docs.append(enrich_doc_manifest(src))
        except Exception as e:
            logger.warning("manifest_load_error", error=str(e))

    return docs


def _file_signature(path: Path) -> tuple[int, int]:
    """Return (mtime_ns, size) for cache invalidation keys."""
    try:
        stat = path.stat()
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (0, 0)


def _build_agent_metadata_cache_key(provider_name: str) -> tuple[Any, ...]:
    """Build a lightweight cache key so metadata refreshes when config/env changes."""
    normalized = str(provider_name or "").strip().lower()

    if normalized == "opencode":
        opencode_bin = shutil.which("opencode") or shutil.which("opencode.exe") or ""
        return (
            normalized,
            _file_signature(OPENCODE_CONFIG_PATH),
            str(opencode_bin),
            str(os.getenv("EXAM_OPENCODE_MODEL") or ""),
            str(os.getenv("EXAM_AGENT_MODEL") or ""),
        )

    if normalized == "openclaw":
        openclaw_config_path = Path(
            os.getenv("EXAM_OPENCLAW_CONFIG_PATH")
            or os.getenv("OPENCLAW_CONFIG_PATH")
            or (PROJECT_DIR / "vendor" / "openclaw-state" / "openclaw.json")
        )
        openclaw_executable = Path(os.getenv("EXAM_OPENCLAW_PATH") or (PROJECT_DIR / "scripts" / "openclaw.sh"))
        return (
            normalized,
            _file_signature(openclaw_config_path),
            _file_signature(openclaw_executable),
            str(os.getenv("EXAM_OPENCLAW_CONFIG_PATH") or ""),
            str(os.getenv("OPENCLAW_CONFIG_PATH") or ""),
            str(os.getenv("EXAM_OPENCLAW_PATH") or ""),
            str(os.getenv("EXAM_OPENCLAW_MODEL") or ""),
            str(os.getenv("EXAM_AGENT_MODEL") or ""),
        )

    if normalized == "codex":
        return (
            normalized,
            str(os.getenv("EXAM_CODEX_MODEL") or ""),
            str(os.getenv("EXAM_OPENAI_MODEL") or ""),
            str(os.getenv("EXAM_AGENT_MODEL") or ""),
        )

    if normalized == "copilot-sdk":
        return (
            normalized,
            str(os.getenv("EXAM_COPILOT_SDK_MODEL") or ""),
            str(os.getenv("EXAM_AGENT_MODEL") or ""),
        )

    return (
        normalized,
        _file_signature(CRUSH_CONFIG_PATH),
        str(os.getenv("EXAM_CRUSH_MODEL") or ""),
        str(os.getenv("EXAM_AGENT_MODEL") or ""),
    )


@st.cache_data(ttl=30, show_spinner=False)
def _load_agent_metadata_cached(provider_name: str, cache_key: tuple[Any, ...]) -> dict:
    """根據 provider 載入對應的模型/MCP/context 設定（供 UI 顯示）"""
    _ = cache_key
    provider_name = str(provider_name or "").strip().lower()
    meta = {
        "model": None,
        "mcp_servers": {},
        "context_paths": [],
        "available_models": [],
    }

    if provider_name == "opencode" and OPENCODE_CONFIG_PATH.exists():
        try:
            with open(OPENCODE_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta["model"] = resolve_opencode_default_model(data)
            meta["mcp_servers"] = data.get("mcp", {})
            meta["available_models"] = collect_opencode_available_models(data)
            # 嘗試從 opencode CLI 取得完整模型清單
            if shutil.which("opencode") or shutil.which("opencode.exe"):
                result = subprocess.run(
                    ["opencode", "models"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode == 0:
                    cli_models = [
                        line.strip()
                        for line in result.stdout.strip().splitlines()
                        if "/" in line.strip() and not line.strip().startswith("Error")
                    ]
                    if cli_models:
                        meta["available_models"] = cli_models
        except Exception as e:
            logger.warning("opencode_config_load_error", error=str(e))
    elif provider_name == "codex":
        codex_model = (
            os.getenv("EXAM_CODEX_MODEL")
            or os.getenv("EXAM_OPENAI_MODEL")
            or os.getenv("EXAM_AGENT_MODEL")
            or "gpt-5.3-codex"
        ).strip()
        meta["model"] = codex_model
        meta["available_models"] = [codex_model]
    elif provider_name == "openclaw":
        openclaw_config_path = Path(
            os.getenv("EXAM_OPENCLAW_CONFIG_PATH")
            or os.getenv("OPENCLAW_CONFIG_PATH")
            or (PROJECT_DIR / "vendor" / "openclaw-state" / "openclaw.json")
        )
        openclaw_executable = Path(os.getenv("EXAM_OPENCLAW_PATH") or (PROJECT_DIR / "scripts" / "openclaw.sh"))

        if openclaw_config_path.exists():
            try:
                with open(openclaw_config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta["model"] = resolve_openclaw_default_model(data)
                meta["available_models"] = collect_openclaw_available_models(data)
                meta["mcp_servers"] = ((data.get("mcp") or {}).get("servers") or {})
                meta["workspace"] = (((data.get("agents") or {}).get("defaults") or {}).get("workspace"))
            except Exception as e:
                logger.warning("openclaw_config_load_error", error=str(e), path=str(openclaw_config_path))

        if openclaw_executable.exists():
            try:
                result = subprocess.run(
                    [str(openclaw_executable), "models", "status", "--plain"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode == 0:
                    cli_model = ""
                    for line in result.stdout.strip().splitlines():
                        if line.strip():
                            cli_model = line.strip()
                    if cli_model:
                        meta["model"] = cli_model
                        if cli_model not in meta["available_models"]:
                            meta["available_models"] = [cli_model, *meta["available_models"]]
            except Exception as e:
                logger.warning("openclaw_model_status_error", error=str(e), path=str(openclaw_executable))
    elif CRUSH_CONFIG_PATH.exists():
        try:
            with open(CRUSH_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "agents" in data and "coder" in data["agents"]:
                meta["model"] = data["agents"]["coder"].get("model")
            meta["mcp_servers"] = data.get("mcp", {})
            if "options" in data:
                meta["context_paths"] = data["options"].get("context_paths", [])
        except Exception as e:
            logger.warning("crush_config_load_error", error=str(e))

    configured_model = get_configured_agent_model(provider_name, meta)
    if configured_model:
        meta["model"] = configured_model
        if configured_model not in meta["available_models"]:
            meta["available_models"] = [configured_model, *meta["available_models"]]

    return meta


def load_agent_metadata(provider_name: str = "crush") -> dict:
    """Load provider metadata with short-lived caching to avoid repeated CLI calls on rerun."""
    cache_key = _build_agent_metadata_cache_key(provider_name)
    return _load_agent_metadata_cached(provider_name, cache_key)


def get_agent_status(provider_name: str, model_override: Optional[str] = None) -> tuple[bool, str, object]:
    """取得 provider 可用狀態"""
    config = AgentProviderConfig.load(
        project_dir=PROJECT_DIR,
        crush_config_path=CRUSH_CONFIG_PATH,
        provider_override=provider_name,
        model_override=model_override,
    )
    try:
        provider = create_agent_provider(config)
    except ValueError as e:
        return False, str(e), None
    available, reason = provider.is_available()
    return available, reason, provider


def check_asset_aware_ready() -> tuple[bool, str]:
    """檢查 asset-aware MCP 實體是否存在"""
    if not ASSET_AWARE_DIR.exists():
        return False, f"缺少目錄：{ASSET_AWARE_DIR}"

    if not any(ASSET_AWARE_DIR.iterdir()):
        return False, "libs/asset-aware-mcp 為空，無法啟動 ingest_documents"

    return True, "asset-aware 目錄存在"


def save_uploaded_pdf(uploaded_file, title_hint: str) -> Path:
    """儲存上傳 PDF 到 data/sources/uploads"""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = (title_hint.strip() or Path(uploaded_file.name).stem).replace(" ", "_")
    target_path = UPLOADS_DIR / f"{timestamp}_{stem}.pdf"

    with open(target_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return target_path


def parse_page_ranges_text(raw_text: str) -> list[str]:
    """將 UI 輸入的頁段字串轉為 page_ranges 參數。"""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        return []

    # 支援中文逗號與空白
    normalized = cleaned.replace("，", ",")
    specs = [part.strip() for part in normalized.split(",") if part.strip()]

    page_ranges: list[str] = []
    for spec in specs:
        if "-" in spec:
            start_text, end_text = spec.split("-", 1)
            start_text = start_text.strip()
            end_text = end_text.strip()
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"頁段格式錯誤：{spec}")
            start_page = int(start_text)
            end_page = int(end_text)
            if start_page < 1 or end_page < 1 or start_page > end_page:
                raise ValueError(f"頁段格式錯誤：{spec}")
            page_ranges.append(f"{start_page}-{end_page}")
        else:
            if not spec.isdigit() or int(spec) < 1:
                raise ValueError(f"頁段格式錯誤：{spec}")
            page_ranges.append(str(int(spec)))

    return page_ranges


def ingest_pdf_via_agent(
    provider,
    pdf_path: Path,
    title: str,
    use_marker: bool,
    page_ranges_text: str,
    marker_max_pages_per_chunk: int,
    extract_figures: bool,
) -> str:
    """透過 agent 觸發 asset-aware 的 ingest_documents"""
    page_ranges = parse_page_ranges_text(page_ranges_text)
    prompt = f"""請使用 MCP 工具 `ingest_documents` 索引 PDF。

參數：
- file_paths: [\"{pdf_path}\"]
- async_mode: false
- use_marker: {str(use_marker).lower()}
- page_ranges: {json.dumps(page_ranges, ensure_ascii=False)}
- marker_max_pages_per_chunk: {int(marker_max_pages_per_chunk)}
- extract_figures: {str(extract_figures).lower()}
- ocr_enabled: false

需求：
- 若 use_marker=true，請保留 blocks.json 以支援精確頁碼/行號來源。
- 若 page_ranges 非空，請只處理指定頁段並在回傳中顯示實際處理頁範圍。
- 大檔時優先遵守 marker_max_pages_per_chunk / extract_figures 參數。
- 完成後回報是否建立了可正式出題的精確來源能力。

完成後請只輸出結果重點（盡量 JSON 或條列）：
1) success（true/false）
2) doc_id
3) use_marker（true/false）
4) source_ready（true/false）
5) message
"""
    return provider.run(prompt)


def _copy_chat_payload_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, ensure_ascii=False))
    return value


def _safe_year_value(value: Any) -> int | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def build_chat_context_label(question: dict, origin_label: str) -> str:
    """Build a short label for the active chat question context."""
    origin = str(origin_label or "題目").strip() or "題目"
    question_number = str(question.get("question_number") or "").strip()
    if question_number:
        origin = f"{origin} 第 {question_number} 題"
    question_text = _truncate_text(str(question.get("question_text") or "").strip(), 48)
    return f"{origin}｜{question_text or '未命名題目'}"


def build_chat_context_payload(question: dict, origin_label: str) -> dict:
    """Normalize a question payload for sidebar discussion."""
    payload = {
        "id": str(question.get("id") or "").strip() or None,
        "question_text": str(question.get("question_text") or "").strip(),
        "options": list(question.get("options") or []),
        "correct_answer": str(question.get("correct_answer") or "").strip(),
        "explanation": str(question.get("explanation") or "").strip(),
        "source": _copy_chat_payload_value(question.get("source") or {}),
        "source_doc_id": question.get("source_doc_id"),
        "source_page": question.get("source_page"),
        "source_page_image_path": question.get("source_page_image_path"),
        "topics": list(question.get("topics") or []),
        "question_type": str(
            question.get("question_type") or question.get("type") or ""
        ).strip(),
        "difficulty": str(question.get("difficulty") or "").strip(),
        "generation_mode": question.get("generation_mode"),
        "preview_only": bool(question.get("preview_only")),
        "formal_save_ready": question.get("formal_save_ready"),
        "evidence_pack": _copy_chat_payload_value(question.get("evidence_pack") or {}),
        "source_confidence": question.get("source_confidence"),
        "exam_name": str(question.get("exam_name") or "").strip(),
        "exam_year": question.get("exam_year"),
        "question_number": question.get("question_number"),
    }
    payload["_chat_origin"] = str(origin_label or "題目").strip() or "題目"
    payload["_chat_label"] = build_chat_context_label(question, payload["_chat_origin"])
    return payload


def set_chat_question_context(question: dict, origin_label: str) -> None:
    """Store one active question for the right-side discussion panel."""
    payload = build_chat_context_payload(question, origin_label)
    st.session_state.chat_question_payload = payload
    st.session_state.chat_question_context_label = payload["_chat_label"]


def clear_chat_question_context() -> None:
    """Clear the active question discussion context."""
    st.session_state.chat_question_payload = None
    st.session_state.chat_question_context_label = "未指定題目"


def get_active_chat_question_context() -> dict | None:
    """Return the active chat question context if one is set."""
    payload = st.session_state.get("chat_question_payload")
    if not isinstance(payload, dict):
        return None
    if not str(payload.get("question_text") or "").strip():
        return None
    return payload


def build_discussion_prompt(user_prompt: str, selected_question: dict | None) -> str:
    """將題目上下文包進聊天 prompt"""
    if not selected_question:
        return user_prompt

    context = {
        "chat_origin": selected_question.get("_chat_origin"),
        "chat_label": selected_question.get("_chat_label"),
        "question_text": selected_question.get("question_text"),
        "options": selected_question.get("options"),
        "correct_answer": selected_question.get("correct_answer"),
        "explanation": selected_question.get("explanation"),
        "source": selected_question.get("source"),
        "source_doc_id": selected_question.get("source_doc_id"),
        "source_page": selected_question.get("source_page"),
        "source_page_image_path": selected_question.get("source_page_image_path"),
        "topics": selected_question.get("topics"),
        "question_type": selected_question.get("question_type"),
        "difficulty": selected_question.get("difficulty"),
        "generation_mode": selected_question.get("generation_mode"),
        "preview_only": selected_question.get("preview_only"),
        "formal_save_ready": selected_question.get("formal_save_ready"),
        "evidence_pack": selected_question.get("evidence_pack"),
        "source_confidence": selected_question.get("source_confidence"),
    }

    return (
        "你正在和使用者討論以下考題，請以這題為主要上下文回答。\n"
        f"題目上下文(JSON): {json.dumps(context, ensure_ascii=False)}\n\n"
        f"使用者問題: {user_prompt}"
    )


def stream_agent_response(prompt: str, provider):
    """聊天用流式回應"""
    for chunk in provider.stream(prompt):
        yield chunk


def run_agent_sync(prompt: str, provider) -> str:
    """聊天用同步回應"""
    return provider.run(prompt)


@st.cache_data(ttl=15, show_spinner=False)
def load_past_exam_catalog(limit: int = 20) -> list[dict]:
    """讀取歷屆考卷清單與摘要資訊。"""
    from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository

    repo = get_past_exam_repository()
    return repo.list_exam_catalog(limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def load_past_exam_questions(past_exam_id: str) -> list[dict]:
    """讀取單份歷屆考卷的題目明細。"""
    from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository

    repo = get_past_exam_repository()
    figure_service = get_past_exam_figure_service()
    questions = repo.list_questions(past_exam_id)
    return [
        figure_service.enrich_question(
            {
                "id": question.id,
                "past_exam_id": question.past_exam_id,
                "question_number": question.question_number,
                "question_text": question.question_text,
                "options": question.options,
                "correct_answer": question.correct_answer,
                "explanation": question.explanation,
                "pattern": question.pattern.value,
                "difficulty": question.difficulty,
                "topics": question.topics,
                "concept_names": question.concept_names,
                "source_doc_id": question.source_doc_id,
                "source_page": question.source_page,
                "exam_name": question.exam_name,
                "exam_year": question.exam_year,
            }
        )
        for question in questions
    ]


def load_past_exam_question_pool(past_exam_ids: list[str]) -> list[dict]:
    """Merge one or more past exams into a single practice pool."""
    question_pool: list[dict] = []
    seen_ids: set[str] = set()

    for past_exam_id in past_exam_ids:
        for question in load_past_exam_questions(past_exam_id):
            question_id = str(question.get("id", "") or "")
            if question_id and question_id in seen_ids:
                continue
            if question_id:
                seen_ids.add(question_id)
            question_pool.append(question)

    return question_pool


@st.cache_data(ttl=5, show_spinner=False)
def load_question_drafts(status: str | None = None, starred_only: bool = False) -> list[dict]:
    """載入題目草稿箱。"""
    from src.application.services.question_draft_service import get_question_draft_service

    return get_question_draft_service().list_drafts(status=status, starred_only=starred_only, limit=300)


@st.cache_data(ttl=5, show_spinner=False)
def get_draft_stats() -> dict:
    """取得草稿箱統計。"""
    from src.application.services.question_draft_service import get_question_draft_service

    return get_question_draft_service().get_statistics()


def build_question_scan_rows(questions: list[dict]) -> list[dict]:
    """建立一般題庫列表的可掃描摘要列。"""
    rows: list[dict] = []
    for index, question in enumerate(questions, start=1):
        topics = question.get("topics", [])
        topic_text = ", ".join(topics[:3]) if topics else "-"
        if len(topics) > 3:
            topic_text += " ..."

        stem = question.get("question_text", "").strip()
        if len(stem) > 42:
            stem = stem[:42].rstrip() + "..."

        rows.append(
            {
                "序": index,
                "題目": stem,
                "難度": question.get("difficulty", "medium"),
                "主題": topic_text,
                "考試類型": (question.get("exam_track") or "-").upper() if question.get("exam_track") else "-",
                "審查": "已審查" if question.get("is_validated") else "待審查",
                "來源": "精確來源" if question_has_precise_source(question) else "待補強",
            }
        )
    return rows


def build_past_exam_scan_rows(past_exams: list[dict]) -> list[dict]:
    """建立歷屆考卷列表的可掃描摘要列。"""
    rows: list[dict] = []
    for exam in past_exams:
        rows.append(
            {
                "年度": exam.get("exam_year", "-"),
                "考卷": exam.get("exam_name", "未命名考卷"),
                "題數": exam.get("total_questions", 0),
                "已有答案": exam.get("answered_questions", 0),
                "來源文件": exam.get("source_doc_id", "-") or "-",
                "狀態": "已分類" if exam.get("is_classified") else "待整理",
            }
        )
    return rows


def update_question_explanation_in_place(questions: list[dict], question_id: str, explanation: str) -> None:
    """Reflect a newly generated explanation inside the current UI payload."""
    cleaned_explanation = str(explanation or "").strip()
    if not cleaned_explanation:
        return

    for question in questions:
        if str(question.get("id") or "") == question_id:
            question["explanation"] = cleaned_explanation
            break


def build_draft_similarity_map(drafts: list[dict], similarity_service, similarity_corpus: list[dict]) -> dict[str, dict]:
    """預先計算草稿列表的相似題摘要，供列表與 promote 摘要重用。"""
    similarity_map: dict[str, dict] = {}
    for draft in drafts:
        draft_id = draft.get("id", "")
        question_text = draft.get("question", {}).get("question_text", "")
        if not draft_id or not question_text.strip():
            similarity_map[draft_id] = {"count": 0, "top_similarity": 0.0, "matches": []}
            continue

        matches = similarity_service.find_similar(
            question_text,
            corpus=similarity_corpus,
            threshold=0.78,
            exclude_ids={draft_id},
        )
        similarity_map[draft_id] = {
            "count": len(matches),
            "top_similarity": matches[0]["similarity"] if matches else 0.0,
            "matches": matches,
        }
    return similarity_map


def build_draft_scan_rows(drafts: list[dict], similarity_map: dict[str, dict] | None = None) -> list[dict]:
    """建立草稿箱列表的可掃描摘要列。"""
    status_labels = {"draft": "草稿", "promoted": "已入庫", "archived": "已封存"}
    confidence_labels = {"precise": "精確來源", "contextual": "全文來源", "none": "無來源"}
    qa_status_labels = {"pending": "待審", "ready": "可入庫", "needs_revision": "需修訂"}
    similarity_map = similarity_map or {}
    rows: list[dict] = []
    for index, draft in enumerate(drafts, start=1):
        question = draft.get("question", {})
        template_data = draft.get("template_data") or {}
        qa_metadata = draft.get("qa_metadata") or {}
        similarity_entry = similarity_map.get(draft.get("id", ""), {})
        similarity_count = int(similarity_entry.get("count", 0) or 0)
        top_similarity = int(round(float(similarity_entry.get("top_similarity", 0.0) or 0.0) * 100))
        topics = question.get("topics", [])
        topic_text = ", ".join(topics[:3]) if topics else "-"
        if len(topics) > 3:
            topic_text += " ..."

        stem = question.get("question_text", "").strip()
        if len(stem) > 42:
            stem = stem[:42].rstrip() + "..."

        rows.append(
            {
                "序": index,
                "星": "⭐" if draft.get("is_starred") else "",
                "狀態": status_labels.get(draft.get("status", "draft"), draft.get("status", "draft")),
                "來源": confidence_labels.get(
                    draft.get("source_confidence", "none"),
                    draft.get("source_confidence", "none"),
                ),
                "題目": stem,
                "模板": template_data.get("label", "-"),
                "QA": qa_status_labels.get(qa_metadata.get("overall_status", "pending"), "待審"),
                "相似題": f"{similarity_count} 筆 / {top_similarity}%" if similarity_count else "-",
                "難度": question.get("difficulty", "medium"),
                "考試類型": (question.get("exam_track") or "-").upper() if question.get("exam_track") else "-",
                "審查": "已審查" if question.get("is_validated") else "待審查",
                "主題": topic_text,
            }
        )
    return rows


def render_draft_workspace(*, show_hero: bool = True) -> None:
    """Render the pending-draft workspace used by the authoring flow."""
    from src.application.services.question_draft_service import get_question_draft_service
    from src.application.services.question_similarity_service import get_question_similarity_service

    draft_service = get_question_draft_service()
    similarity_service = get_question_similarity_service()
    similarity_corpus = similarity_service.build_corpus()
    historical_templates = draft_service.list_historical_templates(limit=12)
    template_map = {template["template_id"]: template for template in historical_templates}
    template_ids = list(template_map.keys())
    draft_status_options = ["全部", "draft", "promoted", "archived"]
    draft_status_labels = {
        "全部": "全部",
        "draft": "草稿",
        "promoted": "已入庫",
        "archived": "已封存",
    }
    qa_status_labels = {
        "pending": "待審",
        "ready": "可入庫",
        "needs_revision": "需修訂",
    }
    qa_check_labels = {
        "pending": "待檢",
        "pass": "通過",
        "revise": "需修訂",
    }
    qa_status_options = ["pending", "ready", "needs_revision"]
    qa_check_options = ["pending", "pass", "revise"]

    render_draft_flash()

    draft_stats = get_draft_stats()
    if show_hero:
        render_page_hero(
            "待審草稿區",
            "生成結果會先落到這裡，再做 QA、批次編修、相似題比對與正式入庫。",
            [
                f"待整理草稿 {draft_stats.get('draft', 0)} 題",
                f"已加星 {draft_stats.get('starred', 0)} 題",
                f"已送入題庫 {draft_stats.get('promoted', 0)} 題",
            ],
        )
    else:
        st.subheader("🗃️ 待審草稿")
        st.caption("生成結果會自動進到這裡；整理好之後再正式入庫。")

    with st.container(border=True):
        st.subheader("歷史題型模板")
        st.caption("可直接拿考古題骨架建立新草稿，或把模板套用到既有待審草稿。")
        if historical_templates:
            selected_template_id = st.selectbox(
                "選擇歷史模板",
                template_ids,
                format_func=lambda template_id: (
                    f"{template_map[template_id]['label']} · {template_map[template_id]['source_exam_year']} 年第 {template_map[template_id]['source_question_number']} 題"
                )
                if template_id in template_map
                else str(template_id),
                key="draft_workspace_selected_template_id",
            ) or template_ids[0]
            selected_template = template_map[selected_template_id]
            template_col1, template_col2 = st.columns([1.55, 1])
            with template_col1:
                st.markdown(f"**骨架題幹:** {selected_template.get('stem_scaffold', '-')}")
                st.caption(
                    f"參考來源：{selected_template.get('source_exam_year', '-')} {selected_template.get('source_exam_name', '')} 第 {selected_template.get('source_question_number', '-')} 題"
                )
                reference_text = selected_template.get("reference_question_text", "")
                if reference_text:
                    if len(reference_text) > 140:
                        reference_text = reference_text[:140].rstrip() + "..."
                    st.caption(f"原始題幹：{reference_text}")
            with template_col2:
                st.markdown(f"**題型:** {selected_template.get('pattern_label', '-')}")
                st.markdown(f"**建議難度:** {selected_template.get('difficulty', '-')}")
                st.markdown(f"**主題:** {', '.join(selected_template.get('topics', [])) or '-'}")
                st.markdown(f"**Bloom:** {selected_template.get('bloom_level', '-')}")

            template_blueprint = selected_template.get("blueprint", {})
            if template_blueprint.get("recommended_rules"):
                st.markdown("**Blueprint 指引**")
                st.markdown(
                    "\n".join(
                        f"- {rule}" for rule in template_blueprint.get("recommended_rules", [])[:3]
                    )
                )

            if st.button("📐 以歷史模板建立新草稿", width="stretch", key="draft_workspace_create_from_template"):
                draft_id = draft_service.create_draft_from_template(selected_template_id)
                if draft_id:
                    invalidate_draft_caches()
                    set_draft_flash(
                        f"已從 {selected_template.get('source_exam_year', '-')} 年第 {selected_template.get('source_question_number', '-')} 題建立模板草稿。"
                    )
                    st.rerun()
                st.error("無法建立模板草稿，請重新整理後再試。")
        else:
            st.info("目前找不到可用的歷史模板，請先確認歷屆題庫是否已匯入。")

    with st.container(border=True):
        filter_col1, filter_col2, filter_col3 = st.columns([1.4, 1, 1])
        with filter_col1:
            draft_search = st.text_input("搜尋草稿", placeholder="輸入題幹、主題或草稿備註", key="draft_workspace_search")
        with filter_col2:
            draft_status = st.selectbox(
                "草稿狀態",
                draft_status_options,
                format_func=lambda x: draft_status_labels.get(x) or str(x),
                index=0,
                key="draft_workspace_status",
            )
        with filter_col3:
            draft_starred_only = st.checkbox("⭐ 只看加星草稿", value=False, key="draft_workspace_starred_only")

    drafts = load_question_drafts(
        status=None if draft_status == "全部" else draft_status,
        starred_only=draft_starred_only,
    )

    if draft_search:
        query = draft_search.strip().lower()
        drafts = [
            draft
            for draft in drafts
            if query in draft.get("question", {}).get("question_text", "").lower()
            or query in " ".join(draft.get("question", {}).get("topics", [])).lower()
            or query in draft.get("notes", "").lower()
        ]

    draft_similarity_map = build_draft_similarity_map(drafts, similarity_service, similarity_corpus)

    if not drafts:
        render_empty_state("待審草稿區目前沒有符合條件的題目", "先在需求/生成分頁出題，或放寬搜尋與篩選條件。")
        return

    st.dataframe(build_draft_scan_rows(drafts, similarity_map=draft_similarity_map), width="stretch", hide_index=True)

    selection_labels = {
        draft["id"]: f"{'⭐ ' if draft.get('is_starred') else ''}[{draft_status_labels.get(draft.get('status', 'draft'), draft.get('status', 'draft'))}] {draft.get('question', {}).get('question_text', '')[:55]}"
        for draft in drafts
    }
    selection_options = list(selection_labels.keys())
    if st.session_state.get("draft_batch_selection_reset_pending"):
        st.session_state.draft_batch_selection_widget = []
        st.session_state.draft_batch_selection_override = []
        st.session_state.draft_batch_selection_reset_pending = False
    st.session_state.draft_batch_selection_widget = [
        draft_id
        for draft_id in st.session_state.get("draft_batch_selection_widget", [])
        if draft_id in selection_options
    ]
    widget_selected_draft_ids = st.multiselect(
        "批次選取草稿",
        options=selection_options,
        format_func=lambda draft_id: selection_labels.get(draft_id) or str(draft_id),
        key="draft_batch_selection_widget",
    )
    selected_draft_ids = widget_selected_draft_ids
    if is_e2e_test_mode() and st.session_state.get("draft_batch_selection_override"):
        selected_draft_ids = [
            draft_id
            for draft_id in st.session_state.get("draft_batch_selection_override", [])
            if draft_id in selection_options
        ]
        st.session_state.draft_batch_selection_override = selected_draft_ids

    if is_e2e_test_mode():
        if st.button("🧪 E2E 全選目前草稿", width="stretch", key="draft_workspace_e2e_select_all"):
            selected_ids = selection_options.copy()
            st.session_state.draft_batch_selection_override = selected_ids
            selected_draft_ids = selected_ids

    if selected_draft_ids:
        selected_drafts = [draft for draft in drafts if draft["id"] in selected_draft_ids]
        qa_ready_count = sum(
            1 for draft in selected_drafts if (draft.get("qa_metadata") or {}).get("overall_status") == "ready"
        )
        qa_revision_count = sum(
            1
            for draft in selected_drafts
            if (draft.get("qa_metadata") or {}).get("overall_status") == "needs_revision"
        )
        similarity_warning_drafts = sum(
            1
            for draft in selected_drafts
            if (draft_similarity_map.get(draft["id"], {}).get("count", 0) or 0) > 0
        )
        with st.container(border=True):
            st.subheader("送入正式題庫前摘要")
            summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
            with summary_col1:
                st.metric("已選草稿", len(selected_drafts))
            with summary_col2:
                st.metric("QA 可入庫", qa_ready_count)
            with summary_col3:
                st.metric("QA 需修訂", qa_revision_count)
            with summary_col4:
                st.metric("相似題警示", similarity_warning_drafts)

            attention_lines = []
            for draft in selected_drafts[:8]:
                qa_status = (draft.get("qa_metadata") or {}).get("overall_status", "pending")
                qa_label = qa_status_labels.get(qa_status, qa_status)
                similarity_entry = draft_similarity_map.get(draft["id"], {})
                similarity_count = int(similarity_entry.get("count", 0) or 0)
                top_similarity = int(round(float(similarity_entry.get("top_similarity", 0.0) or 0.0) * 100))
                if qa_status != "ready" or similarity_count:
                    attention_lines.append(
                        f"- {draft.get('question', {}).get('question_text', '')[:52]}...｜QA: {qa_label}｜相似題: {similarity_count} 筆{f' / {top_similarity}%' if similarity_count else ''}"
                    )

            if attention_lines:
                st.warning("以下草稿在 promote 前建議再確認一次：")
                st.markdown("\n".join(attention_lines))
            else:
                st.info("目前選取草稿沒有相似題或 QA 阻塞訊號，可直接進入 promote。")

    with st.container(border=True):
        st.subheader("批次編修 / 操作")
        edit_col1, edit_col2, edit_col3 = st.columns(3)
        with edit_col1:
            batch_difficulty = st.selectbox("批次難度", ["不變更", "easy", "medium", "hard"], index=0, key="draft_workspace_batch_difficulty")
            batch_validated = st.selectbox(
                "批次審查狀態",
                ["不變更", "設為已審查", "設為待審查"],
                index=0,
                key="draft_workspace_batch_validated",
            )
        with edit_col2:
            batch_exam_track = st.selectbox(
                "批次考試類型",
                ["不變更", "ite", "pgy", "clerk", "specialist", "board", "custom"],
                index=0,
                key="draft_workspace_batch_exam_track",
            )
            batch_starred = st.selectbox(
                "批次星號",
                ["不變更", "加星", "取消加星"],
                index=0,
                key="draft_workspace_batch_starred",
            )
        with edit_col3:
            batch_topics = st.text_input(
                "批次主題標籤",
                placeholder="逗號分隔；留空表示不變更",
                key="draft_workspace_batch_topics",
            )
            batch_notes = st.text_input(
                "批次草稿備註",
                placeholder="留空表示不變更",
                key="draft_workspace_batch_notes",
            )

        template_apply_col1, template_apply_col2 = st.columns([1.8, 1])
        with template_apply_col1:
            batch_template_id = st.selectbox(
                "套用歷史模板到既有草稿",
                ["不套用", *template_ids],
                format_func=lambda template_id: (
                    f"{template_map[template_id]['label']} · {template_map[template_id]['source_exam_year']} 年第 {template_map[template_id]['source_question_number']} 題"
                    if template_id in template_map
                    else str(template_id)
                ),
                key="draft_workspace_batch_template_id",
            )
        with template_apply_col2:
            batch_replace_content = st.checkbox(
                "以模板骨架覆蓋題幹/選項",
                value=False,
                help="若不勾選，只更新模板引用、blueprint 與建議難度/主題。",
                disabled=not template_ids,
                key="draft_workspace_batch_replace_content",
            )

        action_col1, action_col2, action_col3 = st.columns(3)
        with action_col1:
            if st.button("🛠️ 套用批次編修", width="stretch", disabled=not selected_draft_ids, key="draft_workspace_apply_batch_edit"):
                updated = draft_service.bulk_update(
                    draft_ids=selected_draft_ids,
                    difficulty=None if batch_difficulty == "不變更" else batch_difficulty,
                    topics=None if not batch_topics.strip() else [t.strip() for t in batch_topics.split(",") if t.strip()],
                    exam_track=None if batch_exam_track == "不變更" else batch_exam_track,
                    is_validated=None if batch_validated == "不變更" else batch_validated == "設為已審查",
                    is_starred=None if batch_starred == "不變更" else batch_starred == "加星",
                    notes=None if not batch_notes.strip() else batch_notes.strip(),
                )
                invalidate_draft_caches()
                schedule_draft_batch_selection_reset()
                set_draft_flash(f"已更新 {updated} 題草稿。")
                st.rerun()
        with action_col2:
            if st.button("📎 套用歷史模板", width="stretch", disabled=not selected_draft_ids or batch_template_id == "不套用", key="draft_workspace_apply_template"):
                updated = draft_service.apply_template_to_drafts(
                    selected_draft_ids,
                    batch_template_id,
                    replace_content=batch_replace_content,
                )
                invalidate_draft_caches()
                schedule_draft_batch_selection_reset()
                set_draft_flash(f"已將歷史模板套用到 {updated} 題草稿。")
                st.rerun()
        with action_col3:
            if st.button("✅ 送入正式題庫", width="stretch", disabled=not selected_draft_ids, key="draft_workspace_promote"):
                result = draft_service.promote_drafts(selected_draft_ids)
                invalidate_draft_caches()
                invalidate_question_bank_caches()
                schedule_draft_batch_selection_reset()
                promoted_count = int(result.get("promoted", 0) or 0)
                failed_count = len(result.get("failed", []))
                if promoted_count and failed_count:
                    set_draft_flash(
                        f"已正式入庫 {promoted_count} 題，另有 {failed_count} 題入庫失敗。",
                        level="warning",
                    )
                elif promoted_count:
                    set_draft_flash(f"已正式入庫 {promoted_count} 題。")
                elif failed_count:
                    set_draft_flash(f"有 {failed_count} 題入庫失敗。", level="warning")
                st.rerun()

        archive_col1, archive_col2, archive_col3 = st.columns(3)
        with archive_col3:
            if st.button("🗂️ 封存選取", width="stretch", disabled=not selected_draft_ids, key="draft_workspace_archive"):
                archived = draft_service.archive_drafts(selected_draft_ids)
                invalidate_draft_caches()
                schedule_draft_batch_selection_reset()
                set_draft_flash(f"已封存 {archived} 題草稿。")
                st.rerun()

    for index, draft in enumerate(drafts[:40], start=1):
        question = draft.get("question", {})
        template_data = draft.get("template_data") or {}
        blueprint_data = draft.get("blueprint_data") or {}
        qa_data = draft.get("qa_metadata") or {}
        status_label = draft_status_labels.get(draft.get("status", "draft"), draft.get("status", "draft"))
        title_prefix = "⭐ " if draft.get("is_starred") else ""
        with st.expander(f"#{index} {title_prefix}[{status_label}] {question.get('question_text', '')[:58]}..."):
            badges = []
            confidence = draft.get("source_confidence", "none")
            if confidence == "precise":
                badges.append('<span class="status-chip-good">精確來源</span>')
            elif confidence == "contextual":
                badges.append('<span class="status-chip-warn">全文來源</span>')
            else:
                badges.append('<span class="status-chip-warn">無來源</span>')
            if question.get("is_validated"):
                badges.append('<span class="status-chip-good">✅ 已審查</span>')
            else:
                badges.append('<span class="status-chip-warn">待審查</span>')
            if question.get("exam_track"):
                badges.append(f'<span class="status-chip-good">{question["exam_track"].upper()}</span>')
            qa_status = qa_data.get("overall_status", "pending")
            qa_status_label = qa_status_labels.get(qa_status, qa_status)
            if qa_status == "ready":
                badges.append(f'<span class="status-chip-good">QA {qa_status_label}</span>')
            else:
                badges.append(f'<span class="status-chip-warn">QA {qa_status_label}</span>')
            st.markdown(" ".join(badges), unsafe_allow_html=True)

            st.markdown(f"**題目:** {question.get('question_text', '')}")
            for opt_idx, option in enumerate(question.get("options", [])):
                st.markdown(f"- {chr(65 + opt_idx)}. {option}")

            detail_col1, detail_col2, detail_col3 = st.columns(3)
            with detail_col1:
                    answer_letters = _normalize_answer_letters(question.get("correct_answer", "-"), option_count=len(question.get("options") or []))
                    st.markdown(f"**答案:** {_format_answer_letters(answer_letters) or '-'}")
            with detail_col2:
                st.markdown(f"**難度:** {question.get('difficulty', 'medium')}")
            with detail_col3:
                st.markdown(f"**主題:** {', '.join(question.get('topics', [])) or '-'}")

            if question.get("explanation"):
                st.markdown(f"**解析:** {question.get('explanation', '')}")
            if draft.get("notes"):
                st.caption(f"草稿備註：{draft['notes']}")
            if draft.get("promoted_question_id"):
                st.caption(f"正式題庫 ID：{draft['promoted_question_id'][:8]}...")

            if template_data:
                st.markdown("**歷史模板來源**")
                st.caption(
                    f"{template_data.get('label', '-') } · {template_data.get('source_exam_year', '-')} {template_data.get('source_exam_name', '')} 第 {template_data.get('source_question_number', '-')} 題"
                )
                if template_data.get("stem_scaffold"):
                    st.caption(f"模板骨架：{template_data.get('stem_scaffold')}")

            if blueprint_data:
                st.markdown("**Blueprint 摘要**")
                blueprint_col1, blueprint_col2, blueprint_col3 = st.columns(3)
                with blueprint_col1:
                    st.markdown(f"**題型:** {blueprint_data.get('pattern_label') or blueprint_data.get('pattern') or '-'}")
                with blueprint_col2:
                    st.markdown(f"**Bloom:** {blueprint_data.get('bloom_level', '-')}")
                with blueprint_col3:
                    st.markdown(f"**Blueprint 難度:** {blueprint_data.get('difficulty', '-')}")
                if blueprint_data.get("target_topics"):
                    st.caption(f"目標主題：{', '.join(blueprint_data.get('target_topics', []))}")
                if blueprint_data.get("reference_concepts"):
                    st.caption(f"參考概念：{', '.join(blueprint_data.get('reference_concepts', []))}")
                if blueprint_data.get("sample_source_refs"):
                    st.caption(f"歷史參考：{'；'.join(blueprint_data.get('sample_source_refs', []))}")
                if blueprint_data.get("recommended_rules"):
                    st.markdown("\n".join(f"- {rule}" for rule in blueprint_data.get("recommended_rules", [])[:3]))

            similar_matches = draft_similarity_map.get(draft["id"], {}).get("matches", [])
            if similar_matches:
                st.info("相似題提醒")
                match_lines = []
                for match in similar_matches:
                    source_label = "正式題庫" if match["source_type"] == "bank" else "草稿箱"
                    similarity_pct = int(round(match["similarity"] * 100))
                    preview_text = match["question_text"][:72].strip()
                    if len(match["question_text"]) > 72:
                        preview_text += "..."
                    match_lines.append(f"- [{source_label}] {similarity_pct}% 相似: {preview_text}")
                st.markdown("\n".join(match_lines))

            with st.container(border=True):
                st.markdown("**QA 審閱**")
                qa_col1, qa_col2, qa_col3 = st.columns(3)
                with qa_col1:
                    qa_overall = st.selectbox(
                        "整體狀態",
                        qa_status_options,
                        index=qa_status_options.index(qa_data.get("overall_status", "pending"))
                        if qa_data.get("overall_status", "pending") in qa_status_options
                        else 0,
                        format_func=lambda value: qa_status_labels.get(value) or str(value),
                        key=f"draft_qa_overall_{draft['id']}",
                    )
                    qa_stem = st.selectbox(
                        "題幹品質",
                        qa_check_options,
                        index=qa_check_options.index(qa_data.get("stem_quality", "pending"))
                        if qa_data.get("stem_quality", "pending") in qa_check_options
                        else 0,
                        format_func=lambda value: qa_check_labels.get(value) or str(value),
                        key=f"draft_qa_stem_{draft['id']}",
                    )
                with qa_col2:
                    qa_option = st.selectbox(
                        "選項品質",
                        qa_check_options,
                        index=qa_check_options.index(qa_data.get("option_quality", "pending"))
                        if qa_data.get("option_quality", "pending") in qa_check_options
                        else 0,
                        format_func=lambda value: qa_check_labels.get(value) or str(value),
                        key=f"draft_qa_option_{draft['id']}",
                    )
                    qa_answer = st.selectbox(
                        "答案對齊",
                        qa_check_options,
                        index=qa_check_options.index(qa_data.get("answer_alignment", "pending"))
                        if qa_data.get("answer_alignment", "pending") in qa_check_options
                        else 0,
                        format_func=lambda value: qa_check_labels.get(value) or str(value),
                        key=f"draft_qa_answer_{draft['id']}",
                    )
                with qa_col3:
                    qa_source = st.selectbox(
                        "來源對齊",
                        qa_check_options,
                        index=qa_check_options.index(qa_data.get("source_alignment", "pending"))
                        if qa_data.get("source_alignment", "pending") in qa_check_options
                        else 0,
                        format_func=lambda value: qa_check_labels.get(value) or str(value),
                        key=f"draft_qa_source_{draft['id']}",
                    )
                    qa_explanation = st.selectbox(
                        "解析品質",
                        qa_check_options,
                        index=qa_check_options.index(qa_data.get("explanation_quality", "pending"))
                        if qa_data.get("explanation_quality", "pending") in qa_check_options
                        else 0,
                        format_func=lambda value: qa_check_labels.get(value) or str(value),
                        key=f"draft_qa_explanation_{draft['id']}",
                    )

                qa_note = st.text_area(
                    "QA 備註",
                    value=qa_data.get("review_notes", ""),
                    key=f"draft_qa_note_{draft['id']}",
                )
                if qa_data.get("reviewed_at"):
                    reviewer = qa_data.get("reviewer") or "-"
                    st.caption(f"最近審閱：{qa_data.get('reviewed_at')} by {reviewer}")
                st.caption(f"相似題提醒數：{qa_data.get('similarity_warning_count', 0)}")

                if st.button("💾 儲存 QA", key=f"draft_qa_save_{draft['id']}", width="stretch"):
                    saved = draft_service.update_qa_metadata(
                        draft_id=draft["id"],
                        overall_status=qa_overall,
                        stem_quality=qa_stem,
                        option_quality=qa_option,
                        answer_alignment=qa_answer,
                        source_alignment=qa_source,
                        explanation_quality=qa_explanation,
                        review_notes=(qa_note or "").strip(),
                        similarity_warning_count=len(similar_matches),
                    )
                    if saved:
                        invalidate_draft_caches()
                        st.success("QA metadata 已更新。")
                        st.rerun()
                    st.error("QA metadata 更新失敗。")

            history_entries = draft_service.get_draft_history(draft["id"], limit=8)
            if history_entries:
                with st.container(border=True):
                    st.markdown("**版本歷史**")
                    for entry in history_entries:
                        snapshot = entry.get("snapshot_data") or {}
                        snapshot_question = snapshot.get("question") or {}
                        snapshot_template = snapshot.get("template_data") or {}
                        snapshot_qa = snapshot.get("qa_metadata") or {}
                        qa_summary = qa_status_labels.get(
                            snapshot_qa.get("overall_status", "pending"),
                            snapshot_qa.get("overall_status", "pending"),
                        )
                        template_summary = snapshot_template.get("label", "-")
                        reason_text = entry.get("reason") or "-"
                        st.caption(
                            f"v{entry.get('version_number', '-')} · {entry.get('action', '-')} · {entry.get('created_at', '-') } · {entry.get('actor_name', '-') }"
                        )
                        st.markdown(f"- 題目：{snapshot_question.get('question_text', '')[:72] or '-'}")
                        st.markdown(f"- 模板：{template_summary}｜QA：{qa_summary}｜原因：{reason_text}")

            quick_col1, quick_col2 = st.columns(2)
            with quick_col1:
                if st.button(
                    "⭐ 取消加星" if draft.get("is_starred") else "⭐ 加星",
                    key=f"draft_star_{draft['id']}",
                    width="stretch",
                ):
                    draft_service.bulk_update([draft["id"]], is_starred=not draft.get("is_starred", False))
                    invalidate_draft_caches()
                    st.rerun()
            with quick_col2:
                if draft.get("status") == "draft" and st.button(
                    "✅ 立即入庫",
                    key=f"draft_promote_{draft['id']}",
                    width="stretch",
                ):
                    draft_service.promote_drafts([draft["id"]])
                    invalidate_draft_caches()
                    invalidate_question_bank_caches()
                    st.rerun()

            source = question.get("source") or {}
            if source:
                render_source_info(source, expanded=False)


def render_question_review_expander(question: dict, display_number: int, key_prefix: str = "bank") -> None:
    """渲染一般題庫的單題詳情與審查操作。"""
    question_id = question.get("id", str(display_number))
    with st.expander(f"#{display_number} {question.get('question_text', '無題目')[:50]}..."):
        badges = []
        if question.get("is_validated"):
            badges.append('<span class="status-chip-good">✅ 已審查</span>')
        else:
            badges.append('<span class="status-chip-warn">待審查</span>')
        if question_has_precise_source(question):
            badges.append('<span class="status-chip-good">含精確來源</span>')
        else:
            badges.append('<span class="status-chip-warn">來源待補強</span>')
        if question.get("exam_track"):
            badges.append(f'<span class="status-chip-good">{question["exam_track"].upper()}</span>')
        st.markdown(" ".join(badges), unsafe_allow_html=True)

        st.markdown(f"**題目:** {question.get('question_text', '')}")

        st.markdown("**選項:**")
        for idx, option in enumerate(question.get("options", [])):
            prefix = chr(65 + idx)
            st.markdown(f"- {prefix}. {option}")

        meta_col1, meta_col2, meta_col3 = st.columns(3)
        with meta_col1:
            correct_letters = _normalize_answer_letters(question.get("correct_answer", "N/A"), option_count=len(question.get("options") or []))
            st.markdown(f"**答案:** {_format_answer_letters(correct_letters) or '-'}")
        with meta_col2:
            st.markdown(f"**難度:** {question.get('difficulty', 'medium')}")
        with meta_col3:
            st.markdown(f"**知識點:** {', '.join(question.get('topics', [])) or '-'}")

        if question.get("explanation"):
            st.markdown(f"**解析:** {question.get('explanation', '')}")

        review_note = st.text_input(
            "審查備註（可選）",
            value=question.get("validation_notes") or "",
            key=f"{key_prefix}_review_note_{question_id}",
        )
        review_col1, review_col2, review_col3 = st.columns(3)
        with review_col1:
            if st.button("✅ 標記通過", key=f"{key_prefix}_approve_{question_id}", width="stretch"):
                from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

                repo = get_question_repository()
                repo.mark_validated(
                    question_id,
                    passed=True,
                    actor_name="streamlit-admin",
                    notes=review_note or None,
                )
                invalidate_question_bank_caches()
                st.rerun()
        with review_col2:
            if st.button("❌ 標記退回", key=f"{key_prefix}_reject_{question_id}", width="stretch"):
                from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

                repo = get_question_repository()
                repo.mark_validated(
                    question_id,
                    passed=False,
                    actor_name="streamlit-admin",
                    notes=review_note or None,
                )
                invalidate_question_bank_caches()
                st.rerun()
        with review_col3:
            if st.button("🦞 問龍蝦這題", key=f"{key_prefix}_chat_{question_id}", width="stretch"):
                set_chat_question_context(question, "題庫審題")

        source = question.get("source") or {}
        if source:
            render_source_info(source, expanded=False)


@st.cache_data(ttl=10, show_spinner=False)
def get_questions_stats() -> dict:
    """取得題庫統計。"""
    from src.application.services.question_bank_query_service import get_question_bank_query_service

    return get_question_bank_query_service().get_content_stats()


@st.cache_data(ttl=10, show_spinner=False)
def load_questions(validated_only: bool = False, exam_track: str | None = None) -> list[dict]:
    """載入一般題庫題目。"""
    from src.application.services.question_bank_query_service import get_question_bank_query_service

    return get_question_bank_query_service().list_questions(
        validated_only=validated_only,
        exam_track=exam_track,
        limit=500,
    )


@st.cache_data(ttl=5, show_spinner=False)
def load_scope_requests(status: str | None = None) -> list[dict]:
    """載入出題需求 backlog"""
    from src.domain.entities.scope_request import ScopeRequestStatus
    from src.infrastructure.persistence.sqlite_scope_request_repo import get_scope_request_repository

    repo = get_scope_request_repository()
    status_filter = None
    if status:
        try:
            status_filter = ScopeRequestStatus(status)
        except ValueError:
            logger.warning("streamlit_invalid_scope_status_filter", status=status)
            status_filter = None
    requests = repo.list_all(status=status_filter, limit=200)
    return [req.to_dict() for req in requests]


def _clear_cached_read_function(func) -> None:
    """Clear one Streamlit cached read path when a write invalidates it."""
    clear = getattr(func, "clear", None)
    if callable(clear):
        clear()


def invalidate_document_caches() -> None:
    _clear_cached_read_function(load_indexed_documents)


def invalidate_draft_caches() -> None:
    _clear_cached_read_function(load_question_drafts)
    _clear_cached_read_function(get_draft_stats)


def invalidate_question_bank_caches() -> None:
    _clear_cached_read_function(load_questions)
    _clear_cached_read_function(get_questions_stats)


def invalidate_past_exam_caches() -> None:
    _clear_cached_read_function(load_past_exam_catalog)
    _clear_cached_read_function(load_past_exam_questions)


def invalidate_scope_request_caches() -> None:
    _clear_cached_read_function(load_scope_requests)


def get_heartbeat_summary() -> dict:
    """取得 heartbeat / backlog 摘要"""
    from src.application.services.heartbeat_service import HeartbeatService

    return HeartbeatService().get_status_summary()


# ===== 初始化 session state =====
if "messages" not in st.session_state:
    st.session_state.messages = []

configured_agent_provider_name = get_configured_agent_provider_name()
configured_agent_meta = load_agent_metadata(configured_agent_provider_name)
configured_agent_model = get_configured_agent_model(configured_agent_provider_name, configured_agent_meta)

if st.session_state.get("agent_provider_name") != configured_agent_provider_name:
    st.session_state.agent_provider_name = configured_agent_provider_name

if st.session_state.get("_agent_meta_provider_name") != configured_agent_provider_name:
    st.session_state.agent_meta = configured_agent_meta
    st.session_state._agent_meta_provider_name = configured_agent_provider_name

if st.session_state.get("agent_model") != configured_agent_model:
    st.session_state.agent_model = configured_agent_model
    st.session_state.agent_meta["model"] = configured_agent_model

if (
    "agent_available" not in st.session_state
    or "agent_status_reason" not in st.session_state
    or "agent_provider" not in st.session_state
):
    available, reason, provider = get_agent_status(
        st.session_state.agent_provider_name, st.session_state.agent_model or None
    )
    st.session_state.agent_available = available
    st.session_state.agent_status_reason = reason
    st.session_state.agent_provider = provider

if "current_page" not in st.session_state:
    st.session_state.current_page = get_page_from_query_params()
pending_practice_questions = st.session_state.pop("pending_practice_questions", None)
pending_practice_context = st.session_state.pop("pending_practice_context", None)
if pending_practice_questions is not None:
    start_practice_session(pending_practice_questions, pending_practice_context)
pending_page_navigation = st.session_state.pop("pending_page_navigation", None)
if pending_page_navigation in PAGE_OPTIONS:
    st.session_state.current_page = pending_page_navigation
if "page_nav" not in st.session_state:
    st.session_state.page_nav = st.session_state.current_page
skip_query_param_sync_once = bool(st.session_state.pop("skip_query_param_sync_once", False))
if not skip_query_param_sync_once:
    sync_query_params_with_page(st.session_state.current_page)
sync_nav_widget_state()

# 生成狀態
if "generated_questions" not in st.session_state:
    st.session_state.generated_questions = []
if "generated_questions_auto_saved" not in st.session_state:
    st.session_state.generated_questions_auto_saved = False
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False
if st.session_state.pop("pending_generated_review_practice", False) and st.session_state.generated_questions:
    start_practice_session(
        list(st.session_state.generated_questions),
        {
            "source_type": PRACTICE_SOURCE_GENERATED,
            "label": "生成結果",
        },
    )

# 作答練習狀態
if "practice_questions" not in st.session_state:
    st.session_state.practice_questions = []
if "practice_answers" not in st.session_state:
    st.session_state.practice_answers = {}
if "practice_submitted" not in st.session_state:
    st.session_state.practice_submitted = False
if "show_explanations" not in st.session_state:
    st.session_state.show_explanations = {}
if "practice_context" not in st.session_state:
    st.session_state.practice_context = {}
if "etl_last_result" not in st.session_state:
    st.session_state.etl_last_result = ""
if "last_generation_response" not in st.session_state:
    st.session_state.last_generation_response = ""
if "chat_question_payload" not in st.session_state:
    st.session_state.chat_question_payload = None
if "chat_question_context_label" not in st.session_state:
    st.session_state.chat_question_context_label = "未指定題目"
if "chat_active_job_id" not in st.session_state:
    st.session_state.chat_active_job_id = None
if "chat_active_assistant_index" not in st.session_state:
    st.session_state.chat_active_assistant_index = None
if "draft_flash" not in st.session_state:
    st.session_state.draft_flash = ""
if "draft_flash_level" not in st.session_state:
    st.session_state.draft_flash_level = "success"
if "draft_batch_selection_widget" not in st.session_state:
    st.session_state.draft_batch_selection_widget = []
if "draft_batch_selection_override" not in st.session_state:
    st.session_state.draft_batch_selection_override = []
if "draft_batch_selection_reset_pending" not in st.session_state:
    st.session_state.draft_batch_selection_reset_pending = False


content_stats = get_questions_stats()


with st.sidebar:
    st.title("🩺 考卷生成系統")
    st.caption("教材索引、題目生成、題庫管理與互動練習整合工作台")
    st.markdown("---")

    # 導航
    st.subheader("📌 導航")
    st.radio(
        "選擇頁面",
        PAGE_OPTIONS,
        key="page_nav",
        on_change=sync_current_page_from_nav,
        label_visibility="collapsed",
    )
    page = st.session_state.current_page

    st.markdown("---")

    with st.container(border=True):
        st.subheader("🤖 Agent 控制台")
        st.caption("Provider / 模型由伺服器設定固定，前端不提供切換。")
        st.markdown(f"**固定 Provider:** {st.session_state.agent_provider_name}")
        st.markdown(f"**固定模型:** {st.session_state.agent_model or 'N/A'}")

        if st.session_state.agent_provider_name not in SUPPORTED_AGENT_PROVIDERS:
            st.warning("目前 repo 尚未實作此 provider；需補 provider adapter 與可用執行環境後才能連線。")

        status = "🟢 已連線" if st.session_state.agent_available else "🔴 未連線"
        st.markdown(f"**Agent 狀態:** {status}")
        st.caption(f"Provider: {st.session_state.agent_provider_name}")
        st.caption(f"狀態訊息: {st.session_state.agent_status_reason}")
        mcp_status = (
            "可用"
            if provider_supports_repo_mcp(st.session_state.agent_provider_name, st.session_state.agent_meta)
            else "未接通"
        )
        st.caption(f"Repo MCP 工具: {mcp_status}")

        if st.session_state.agent_model:
            st.caption(f"模型: {st.session_state.agent_model}")
        if st.session_state.agent_meta.get("workspace"):
            st.caption(f"Workspace: {st.session_state.agent_meta['workspace']}")

        if st.session_state.agent_meta.get("mcp_servers"):
            with st.expander("MCP Servers"):
                for name in st.session_state.agent_meta["mcp_servers"].keys():
                    st.caption(f"• {name}")

        mcp_ok, mcp_msg = check_asset_aware_ready()
        st.caption(f"asset-aware: {'✅' if mcp_ok else '⚠️'} {mcp_msg}")

        if st.button("🔄 重新連線", width="stretch"):
            st.session_state.agent_meta = load_agent_metadata(st.session_state.agent_provider_name)
            available, reason, provider = get_agent_status(
                st.session_state.agent_provider_name, st.session_state.agent_model or None
            )
            st.session_state.agent_available = available
            st.session_state.agent_status_reason = reason
            st.session_state.agent_provider = provider
            st.rerun()

    with st.container(border=True):
        st.subheader("📈 內容概況")
        st.metric("一般題庫", content_stats["regular_question_count"])
        st.metric("歷屆題庫", content_stats["past_exam_question_count"])
        st.metric("歷屆考卷", content_stats["past_exam_count"])
        if content_stats["generated_exam_count"]:
            st.caption(f"另有 {content_stats['generated_exam_count']} 份練習考卷檔。")
        st.caption("一般題庫 = AI / 正式題；歷屆題庫 = 匯入考古題。")


_chat_panel_fragment = st.fragment if hasattr(st, "fragment") else (lambda func: func)


def get_chat_stream_jobs():
    """Return the per-session chat stream job store."""
    return ensure_chat_stream_job_store(st.session_state)


def rerun_chat_panel() -> None:
    """Prefer fragment-local reruns for chat interactions, with older Streamlit fallback."""
    try:
        st.rerun(scope="fragment")
    except TypeError:
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        if "fragment" in str(exc).lower() or "scope" in str(exc).lower():
            st.rerun()
        raise


def sync_active_chat_stream() -> None:
    """Refresh the in-flight assistant message from the background stream job."""
    job_id = str(st.session_state.get("chat_active_job_id") or "").strip()
    assistant_index = st.session_state.get("chat_active_assistant_index")
    if not job_id or not isinstance(assistant_index, int):
        return

    job_store = get_chat_stream_jobs()
    messages = st.session_state.get("messages") or []
    if assistant_index < 0 or assistant_index >= len(messages):
        job_store.cancel(job_id, reason="stream target message missing")
        logger.warning(
            "chat_stream_target_missing",
            job_id=job_id,
            assistant_index=assistant_index,
            message_count=len(messages),
        )
        st.session_state.chat_active_job_id = None
        st.session_state.chat_active_assistant_index = None
        return

    snapshot = job_store.snapshot(job_id)
    message = messages[assistant_index]
    streamed_content = str(snapshot.get("content") or "")
    status = str(snapshot.get("status") or "error")
    error_message = str(snapshot.get("error") or "")

    if streamed_content:
        message["content"] = streamed_content

    if status == "running":
        message["streaming"] = True
        return

    message.pop("streaming", None)
    if status == "done":
        if not str(message.get("content") or "").strip():
            message["content"] = "無回應"
    elif status == "cancelled":
        if not str(message.get("content") or "").strip():
            message["content"] = f"[中止] {error_message or '回應已停止'}"
    else:
        if is_missing_chat_job_error(error_message):
            logger.warning("chat_stream_job_missing", job_id=job_id, assistant_index=assistant_index)
        fallback_error = build_chat_stream_error_message(error_message)
        if streamed_content:
            message["content"] = f"{streamed_content}\n\n{fallback_error}"
        else:
            message["content"] = fallback_error

    logger.info(
        "chat_stream_terminal",
        job_id=job_id,
        assistant_index=assistant_index,
        status=status,
        content_len=len(str(message.get("content") or "")),
        error=error_message,
    )
    st.session_state.chat_active_job_id = None
    st.session_state.chat_active_assistant_index = None


def stop_active_chat_stream(reason: str = "回應已停止") -> None:
    """Stop tracking the current stream and recover the chat UI immediately."""
    job_id = str(st.session_state.get("chat_active_job_id") or "").strip()
    assistant_index = st.session_state.get("chat_active_assistant_index")
    messages = st.session_state.get("messages") or []

    if job_id:
        cancelled = get_chat_stream_jobs().cancel(job_id, reason=reason)
        logger.info(
            "chat_stream_cancel_requested",
            job_id=job_id,
            assistant_index=assistant_index,
            cancelled=cancelled,
            reason=reason,
        )

    if isinstance(assistant_index, int) and 0 <= assistant_index < len(messages):
        message = messages[assistant_index]
        message.pop("streaming", None)
        if not str(message.get("content") or "").strip():
            message["content"] = f"[中止] {reason}"

    st.session_state.chat_active_job_id = None
    st.session_state.chat_active_assistant_index = None


@_chat_panel_fragment
def render_chat_panel(current_page: str) -> None:
    """Render the persistent assistant panel behind a fragment rerun boundary."""
    _ = current_page
    sync_active_chat_stream()
    chat_stream_running = bool(st.session_state.get("chat_active_job_id"))

    with st.container(border=True):
        st.subheader("💬 AI 助手")

        selected_question = get_active_chat_question_context()
        if selected_question:
            source_state = "精確來源可用" if question_has_precise_source(selected_question) else "來源待補強"
            context_col1, context_col2 = st.columns([3.4, 1])
            with context_col1:
                st.caption(f"目前上下文：{st.session_state.chat_question_context_label} · {source_state}")
            with context_col2:
                if st.button("清除題目", key="chat_context_clear", width="stretch"):
                    clear_chat_question_context()
                    rerun_chat_panel()
        else:
            st.caption("目前上下文：未指定題目。請在作答、審題或生成預覽按「🦞 問龍蝦這題」。")

        quick_prompt = ""
        if not st.session_state.messages:
            render_empty_state("從右側開始即時討論", "你可以詢問題目詳解、誘答選項設計，或請 AI 幫你檢查目前工作流。")
            qp_col1, qp_col2, qp_col3 = st.columns(3)
            if qp_col1.button("流程建議", width="stretch"):
                quick_prompt = CHAT_QUICK_PROMPTS[0]
            if qp_col2.button("檢查詳解", width="stretch"):
                quick_prompt = CHAT_QUICK_PROMPTS[1]
            if qp_col3.button("審閱清單", width="stretch"):
                quick_prompt = CHAT_QUICK_PROMPTS[2]

        chat_container = st.container(height=compute_chat_history_height(len(st.session_state.messages)))
        with chat_container:
            active_idx = st.session_state.get("chat_active_assistant_index")
            for message_index, message in enumerate(st.session_state.messages):
                with st.chat_message(message["role"]):
                    content = str(message.get("content") or "")
                    if chat_stream_running and message_index == active_idx and message.get("role") == "assistant":
                        st.markdown(content + "▌" if content else "▌")
                    else:
                        st.markdown(content)

        if not st.session_state.agent_available:
            st.warning("⚠️ Agent 未連線")

        prompt = st.chat_input(
            "輸入問題...",
            key="chat_input",
            disabled=(not st.session_state.agent_available) or chat_stream_running,
        )
        if quick_prompt:
            prompt = quick_prompt

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt, "timestamp": datetime.now().isoformat()})

        if st.session_state.agent_available:
            effective_prompt = build_discussion_prompt(prompt, selected_question)
            st.session_state.messages.append(
                {"role": "assistant", "content": "", "timestamp": datetime.now().isoformat(), "streaming": True}
            )
            assistant_index = len(st.session_state.messages) - 1
            try:
                provider = st.session_state.agent_provider
                if provider is None:
                    raise RuntimeError("agent provider unavailable")
                job_id = get_chat_stream_jobs().start(
                    lambda _prompt=effective_prompt, _provider=provider: stream_agent_response(_prompt, _provider)
                )
                logger.info(
                    "chat_stream_start",
                    job_id=job_id,
                    provider=st.session_state.agent_provider_name,
                    prompt_len=len(prompt),
                    effective_prompt_len=len(effective_prompt),
                    has_question_context=bool(selected_question),
                )
                st.session_state.chat_active_job_id = job_id
                st.session_state.chat_active_assistant_index = assistant_index
            except Exception as exc:  # noqa: BLE001
                st.session_state.messages[assistant_index]["content"] = build_chat_stream_error_message(str(exc))
                st.session_state.messages[assistant_index].pop("streaming", None)
                st.session_state.chat_active_job_id = None
                st.session_state.chat_active_assistant_index = None
        else:
            st.session_state.messages.append(
                {"role": "assistant", "content": "[錯誤] Agent 未連線", "timestamp": datetime.now().isoformat()}
            )

        rerun_chat_panel()

    if chat_stream_running or st.session_state.messages:
        action_col1, action_col2 = st.columns(2)
        with action_col1:
            if chat_stream_running and st.button("⏹️ 停止回應", key="chat_stop_stream", width="stretch"):
                stop_active_chat_stream("使用者中止回應")
                rerun_chat_panel()
        with action_col2:
            if st.session_state.messages and st.button("🗑️ 清除對話", width="stretch"):
                if chat_stream_running:
                    stop_active_chat_stream("使用者清除對話")
                st.session_state.messages = []
                rerun_chat_panel()

    if chat_stream_running:
        time.sleep(0.15)
        rerun_chat_panel()


# ===== 主區域：三欄佈局 (操作區 2/3 + 常駐 Chat 1/3) =====
main_col, chat_col = st.columns([2, 1], gap="medium")


# ===== 左欄：操作區內容 =====
with main_col:
    if page == WORKBENCH_PAGE:
        # ===== 考題生成頁面 =====
        indexed_docs_snapshot = load_indexed_documents()
        precise_doc_count = sum(1 for doc in indexed_docs_snapshot if doc.get("has_precise_sources"))
        render_page_hero(
            "AI 考題生成",
            "把需求填寫、教材選擇、考古題骨架與生成結果預覽收進同一個工作台；待審、QA 與正式入庫統一在題庫管理處理。",
            [
                f"已索引教材 {len(indexed_docs_snapshot)} 份",
                f"精確來源教材 {precise_doc_count} 份",
                f"Agent：{st.session_state.agent_provider_name}",
            ],
        )

        if indexed_docs_snapshot and precise_doc_count == 0:
            st.warning(
                "目前 0 份教材具備精確來源能力。若要正式來源追蹤，請先用 Marker 重新索引至少一份教材，再開始正式生成。"
            )

        # 分成上下兩區：配置區 + 預覽區
        config_section, preview_section = st.container(), st.container()
        selected_docs_info: list[dict] = []
        selected_doc_ids: list[str] = []
        selected_section_details: list[dict] = []
        source_doc = ""
        source_mode = SOURCE_MODE_OPTIONS[0]
        strict_source_tracking = False
        preview_only_mode = False
        missing_precise_docs: list[dict] = []
        selected_template_context: dict | None = None

        with config_section:
            with st.container(border=True):
                st.subheader("Step 1. 選擇來源模式")
                source_mode = st.selectbox(
                    "來源模式",
                    SOURCE_MODE_OPTIONS,
                    index=0,
                    help="明確指定這一批題目要依據既有教材、先 ingest 新教材，或用歷史考古題骨架改寫。",
                )

                if source_mode == SOURCE_MODE_EXISTING:
                    st.caption("直接使用 server 內已拆解完成的教材與章節範圍出題。")
                    st.markdown(
                        '<div class="section-note">這個模式適合已完成 ETL 的教材；若教材具備 Marker blocks，可進行 page / line / bbox 級的來源驗證。</div>',
                        unsafe_allow_html=True,
                    )
                elif source_mode == SOURCE_MODE_UPLOAD:
                    st.caption("先上傳新教材完成 ETL，再回到下方從已索引教材清單挑選這次要用的來源。")
                    st.markdown(
                        '<div class="section-note">正式來源追蹤建議開啟 Marker 模式。它比較慢，但會保留 blocks.json，之後才能做 page / line / bbox 級的題目來源驗證。</div>',
                        unsafe_allow_html=True,
                    )

                    etl_col1, etl_col2 = st.columns([1.4, 1])
                    with etl_col1:
                        uploaded_pdf = st.file_uploader("上傳教材 PDF", type=["pdf"], key="etl_pdf")
                        etl_title = st.text_input(
                            "教材標題",
                            placeholder="如：Miller's Anesthesia 9th",
                            key="etl_title",
                        )
                        etl_page_ranges = st.text_input(
                            "頁段範圍（可選）",
                            placeholder="例：1-50,120-160（留空 = 全文）",
                            key="etl_page_ranges",
                            help="指定 ingest_documents 的 page_ranges；可用單頁（8）或區間（1-50），多段以逗號分隔。",
                        )
                    with etl_col2:
                        etl_use_marker = st.toggle(
                            "精確來源模式（Marker）",
                            value=True,
                            help="開啟後會以 Marker 解析 PDF，保留 blocks.json，供正式出題時做精確來源追蹤。",
                        )
                        if etl_use_marker:
                            st.caption("適合正式出題與詳解引用，速度較慢。")
                        else:
                            st.caption("適合快速預覽，通常只保留全文 markdown。")

                        etl_chunk_pages = st.number_input(
                            "大檔分塊頁數（0 = 自動/整本）",
                            min_value=0,
                            max_value=400,
                            value=0,
                            step=10,
                            disabled=not etl_use_marker,
                            help="對應 marker_max_pages_per_chunk。建議超大 PDF 可設 50-120。",
                        )
                        etl_extract_figures = st.toggle(
                            "擷取圖像 assets",
                            value=True,
                            disabled=not etl_use_marker,
                            help="對應 extract_figures。圖片很多時可先關閉以降低記憶體壓力。",
                        )

                    if st.button("⚙️ 執行 ETL（ingest_documents）", width="stretch"):
                        if not provider_supports_repo_mcp(
                            st.session_state.agent_provider_name,
                            st.session_state.agent_meta,
                        ):
                            st.error("ETL 需要支援 repo MCP 工具的 agent；請先確認目前 provider 已完成 repo bootstrap。")
                        elif not st.session_state.agent_available:
                            st.error("Agent 未連線，無法執行 ETL。")
                        elif uploaded_pdf is None:
                            st.error("請先上傳 PDF 檔案。")
                        elif not etl_title.strip():
                            st.error("請輸入教材標題。")
                        else:
                            mcp_ok, mcp_msg = check_asset_aware_ready()
                            if not mcp_ok:
                                st.error(f"asset-aware MCP 不可用：{mcp_msg}")
                            else:
                                with st.spinner("正在上傳並觸發 ingest_documents..."):
                                    try:
                                        saved_path = save_uploaded_pdf(uploaded_pdf, etl_title)
                                        result_text = ingest_pdf_via_agent(
                                            st.session_state.agent_provider,
                                            saved_path,
                                            etl_title.strip(),
                                            etl_use_marker,
                                            etl_page_ranges,
                                            int(etl_chunk_pages),
                                            bool(etl_extract_figures),
                                        )
                                        st.session_state.etl_last_result = result_text
                                        invalidate_document_caches()
                                        st.success("ETL 已觸發，請在下方已索引教材清單選擇剛剛 ingest 的教材。")
                                        st.code(result_text)
                                    except ValueError as e:
                                        st.error(f"ETL 參數錯誤：{e}")
                                    except Exception as e:
                                        st.error(f"ETL 失敗：{e}")

                    if st.session_state.etl_last_result:
                        with st.expander("最近一次 ETL 回傳", expanded=False):
                            st.code(st.session_state.etl_last_result)
                else:
                    from src.application.services.question_draft_service import get_question_draft_service

                    preview_only_mode = True
                    draft_service = get_question_draft_service()
                    historical_templates = draft_service.list_historical_templates(limit=12)
                    template_map = {template["template_id"]: template for template in historical_templates}
                    template_ids = list(template_map.keys())

                    st.caption("直接拿歷史考古題的題型骨架改寫；這批結果會先保留為預覽，後續在題庫管理補來源與 QA。")
                    if historical_templates:
                        selected_template_id = st.selectbox(
                            "歷史模板",
                            template_ids,
                            format_func=lambda template_id: (
                                f"{template_map[template_id]['label']} · {template_map[template_id]['source_exam_year']} 年第 {template_map[template_id]['source_question_number']} 題"
                            )
                            if template_id in template_map
                            else str(template_id),
                            key="generation_selected_template_id",
                        )
                        selected_template_context = template_map.get(selected_template_id)

                        if selected_template_context:
                            template_col1, template_col2 = st.columns([1.45, 1])
                            with template_col1:
                                st.markdown(
                                    f"**骨架題幹:** {selected_template_context.get('stem_scaffold', '-')}"
                                )
                                st.caption(
                                    f"參考來源：{selected_template_context.get('source_exam_year', '-')} 年 {selected_template_context.get('source_exam_name', '')} 第 {selected_template_context.get('source_question_number', '-')} 題"
                                )
                                reference_text = selected_template_context.get("reference_question_text", "")
                                if reference_text:
                                    if len(reference_text) > 160:
                                        reference_text = reference_text[:160].rstrip() + "..."
                                    st.caption(f"原始題幹：{reference_text}")
                            with template_col2:
                                st.markdown(f"**題型骨架:** {selected_template_context.get('pattern_label', '-')}")
                                st.markdown(f"**建議難度:** {selected_template_context.get('difficulty', '-')}")
                                st.markdown(
                                    f"**主題:** {', '.join(selected_template_context.get('topics', [])) or '-'}"
                                )
                                st.markdown(f"**Bloom:** {selected_template_context.get('bloom_level', '-')}")

                            template_blueprint = selected_template_context.get("blueprint", {})
                            if template_blueprint.get("recommended_rules"):
                                st.markdown("**Blueprint 指引**")
                                st.markdown(
                                    "\n".join(
                                        f"- {rule}"
                                        for rule in template_blueprint.get("recommended_rules", [])[:4]
                                    )
                                )
                    else:
                        st.info("目前找不到可用的歷史模板，請先確認歷屆題庫是否已匯入。")

            with st.container(border=True):
                st.subheader("Step 2. 設定出題條件")
                st.caption("先定義題型與難度，再依來源模式補齊教材或模板範圍。每題生成時就必須一併產出詳解。")
                st.markdown("##### 2-1 出題條件")

                col1, col2 = st.columns(2)

                with col1:
                    question_type = st.selectbox(
                        "題型",
                        ["單選題", "多選題", "是非題"],
                        index=0,
                    )

                    difficulty = st.select_slider(
                        "難度",
                        options=["簡單", "中等", "困難"],
                        value="中等",
                    )

                with col2:
                    num_questions = st.number_input(
                        "題數",
                        min_value=1,
                        max_value=20,
                        value=5,
                    )

                    topics = st.multiselect(
                        "知識點範圍（可選）",
                        ["全身麻醉", "局部麻醉", "藥理學", "生理學", "監測", "疼痛醫學", "重症加護"],
                        default=[],
                    )

                    prompt_preset = st.selectbox(
                        "Prompt Preset",
                        ["無"] + list(PROMPT_PRESETS.keys()),
                        index=0,
                        help="快速套用出題/詳解風格",
                    )

                st.markdown("---")

                indexed_docs = indexed_docs_snapshot
                st.markdown("##### 2-2 依來源模式設定題材")

                if source_mode in (SOURCE_MODE_EXISTING, SOURCE_MODE_UPLOAD) and indexed_docs:
                    doc_label_map: dict[str, dict] = {}
                    doc_labels: list[str] = []
                    for d in indexed_docs:
                        title = d.get("title", d.get("doc_id", "未知"))
                        doc_id = d.get("doc_id", "")
                        pages = d.get("page_count", "?")
                        mode = "精確" if d.get("has_precise_sources") else "全文"
                        label = f"{title} ({pages}p / {mode}) [{doc_id[:12]}]"
                        doc_labels.append(label)
                        doc_label_map[label] = d

                    if source_mode == SOURCE_MODE_UPLOAD:
                        st.caption("ETL 完成後，請在這裡選擇剛剛 ingest 的教材；也可以同時搭配其他已索引教材。")
                    else:
                        st.caption("選擇已拆解教材後，可再細選章節範圍。")

                    selected_doc_labels = st.multiselect(
                        "📚 參考教材（已索引，可多選）",
                        options=doc_labels,
                        default=doc_labels[:1] if len(doc_labels) == 1 else [],
                        help="選擇已索引的教材，系統會先檢查是否具備精確來源能力。",
                    )

                    for label in selected_doc_labels:
                        m = doc_label_map[label]
                        selected_docs_info.append(
                            {
                                "doc_id": m.get("doc_id", ""),
                                "title": m.get("title", ""),
                                "sections": m.get("assets", {}).get("sections", []),
                                "toc": m.get("toc", []),
                                "page_count": m.get("page_count", "?"),
                                "has_precise_sources": m.get("has_precise_sources", False),
                            }
                        )

                    all_section_options: list[str] = []
                    section_label_map: dict[str, dict] = {}
                    for doc_info in selected_docs_info:
                        doc_title_short = doc_info["title"][:30]
                        for sec in doc_info["sections"]:
                            indent = "  " * (sec.get("level", 1) - 1)
                            sec_label = f"{indent}{sec['title']} (P.{sec.get('page', '?')})"
                            if len(selected_docs_info) > 1:
                                sec_label = f"[{doc_title_short}] {sec_label}"
                            all_section_options.append(sec_label)
                            section_label_map[sec_label] = {
                                **sec,
                                "doc_id": doc_info["doc_id"],
                                "doc_title": doc_info["title"],
                            }

                    selected_sections: list[str] = []
                    if all_section_options:
                        selected_sections = st.multiselect(
                            "📑 指定章節範圍（可多選，空 = 全文）",
                            options=all_section_options,
                            default=[],
                            help="選擇特定章節讓 AI 聚焦出題，留空則使用全文",
                        )

                    if selected_docs_info:
                        source_doc = ", ".join(d["title"] for d in selected_docs_info)
                        selected_doc_ids = [d["doc_id"] for d in selected_docs_info]
                        selected_section_details = [section_label_map[s] for s in selected_sections]

                        strict_source_tracking = st.toggle(
                            "嚴格來源追蹤（正式題庫模式）",
                            value=True,
                            help="開啟後，若教材缺少 Marker blocks，就不允許正式生成；關閉後可改為 preview-only 模式。",
                        )

                        precise_ready_count, _missing_precise_count = render_selected_docs_summary(selected_docs_info)
                        missing_precise_docs = [doc for doc in selected_docs_info if not doc.get("has_precise_sources")]
                        preview_only_mode = bool(missing_precise_docs) and not strict_source_tracking

                        if missing_precise_docs:
                            missing_titles = ", ".join(doc["title"] for doc in missing_precise_docs)
                            if strict_source_tracking:
                                st.error(
                                    f"正式模式無法使用目前教材：{missing_titles}。請先用 Marker 重新 ingest，或切換為 preview-only 模式。"
                                )
                            else:
                                st.warning(
                                    f"目前為 preview-only 模式：{missing_titles} 缺少精確來源，系統只會生成可審閱題目，不應直接視為正式入庫題。"
                                )
                        elif precise_ready_count:
                            st.success("已選教材都具備精確來源能力，可走正式來源追蹤流程。")
                elif source_mode in (SOURCE_MODE_EXISTING, SOURCE_MODE_UPLOAD):
                    if source_mode == SOURCE_MODE_UPLOAD:
                        st.warning("⚠️ 尚無已索引教材。請先在上方上傳 PDF 並執行 ETL。")
                    else:
                        st.warning("⚠️ 尚無已拆解教材可選。若要用教材出題，請先切到「先上傳新教材再出題」完成 ETL。")
                    preview_only_mode = True
                else:
                    preview_only_mode = True
                    if selected_template_context:
                        st.success(
                            "目前將以歷史模板改寫模式生成；結果會先保留為預覽，後續請到題庫管理做相似題比對與正式入庫。"
                        )
                    else:
                        st.warning("⚠️ 目前尚未選定歷史模板。")

                additional_instructions = st.text_area(
                    "額外指示（可選）",
                    placeholder="如：請包含臨床案例分析...",
                    height=100,
                )

                generation_blocked = False
                if source_mode == SOURCE_MODE_TEMPLATE:
                    generation_blocked = selected_template_context is None
                elif not provider_supports_repo_mcp(
                    st.session_state.agent_provider_name,
                    st.session_state.agent_meta,
                ):
                    generation_blocked = True
                elif not selected_doc_ids:
                    generation_blocked = True
                elif strict_source_tracking and missing_precise_docs:
                    generation_blocked = True

                st.markdown("##### Step 3. 確認模式並開始生成")
                if source_mode == SOURCE_MODE_TEMPLATE:
                    st.info("目前是模板改寫模式：會先生成預覽題目，審題與正式入庫請到題庫管理。")
                elif not provider_supports_repo_mcp(
                    st.session_state.agent_provider_name,
                    st.session_state.agent_meta,
                ):
                    st.warning("目前 provider 未接通 repo MCP 工具；教材 ETL、知識檢索與教材出題流程暫時無法使用。")
                elif preview_only_mode:
                    st.info("目前是 preview-only 模式：可先驗證內容方向，但不應視為正式入庫題。")
                elif selected_doc_ids:
                    st.success("目前符合正式來源追蹤條件，可直接開始正式生成。")
                else:
                    st.warning("請先依來源模式完成來源選擇，再開始生成。")

                submitted = st.button(
                    "🚀 開始生成",
                    key="start_generation",
                    width="stretch",
                    type="primary",
                    disabled=generation_blocked,
                )

        # 預覽區
        with preview_section:
            if submitted:
                if not st.session_state.agent_available:
                    st.error("❌ Agent 未連線，無法生成")
                elif source_mode != SOURCE_MODE_TEMPLATE and not provider_supports_repo_mcp(
                    st.session_state.agent_provider_name,
                    st.session_state.agent_meta,
                ):
                    st.error("❌ 目前 provider 未接通 repo MCP 工具；教材出題流程暫時無法使用。")
                elif source_mode == SOURCE_MODE_TEMPLATE and not selected_template_context:
                    st.error("❌ 目前尚未選定歷史模板。")
                elif source_mode != SOURCE_MODE_TEMPLATE and not selected_doc_ids:
                    st.error("❌ 請先依來源模式選擇至少一份已索引教材。")
                elif selected_doc_ids and strict_source_tracking and missing_precise_docs:
                    missing_titles = ", ".join(doc["title"] for doc in missing_precise_docs)
                    st.error(f"❌ 目前選到的教材仍缺少精確來源：{missing_titles}")
                else:
                    # 清空之前的生成結果
                    st.session_state.generated_questions = []
                    st.session_state.is_generating = True

                    textbook_context_bundle: dict = {}
                    if selected_doc_ids:
                        from src.application.services.textbook_generation_service import get_textbook_generation_service

                        textbook_context_bundle = get_textbook_generation_service().build_prompt_context(
                            selected_doc_ids,
                            selected_section_details,
                        )

                    prompt = build_generation_prompt(
                        num_questions=num_questions,
                        question_type=question_type,
                        difficulty=difficulty,
                        topics=topics,
                        source_doc=source_doc,
                        selected_doc_ids=selected_doc_ids,
                        preview_only_mode=preview_only_mode,
                        selected_section_details=selected_section_details,
                        additional_instructions=additional_instructions,
                        prompt_preset=prompt_preset,
                        prompt_presets=PROMPT_PRESETS,
                        prompt_context=textbook_context_bundle.get("prompt_context", ""),
                        source_mode=source_mode,
                        template_context=selected_template_context,
                    )

                    provider = st.session_state.agent_provider
                    provider_name = getattr(provider, "name", "unknown")
                    logger.info("ui_generation_start", num_questions=num_questions, provider=provider_name)

                    generation_ui = create_generation_execution_ui()

                    full_response, saved_questions = stream_agent_generate(
                        prompt=prompt,
                        provider=provider,
                        execution_ui=generation_ui,
                    )

                    # 更新 session state
                    st.session_state.is_generating = False

                    # === 題目提取流程（三層策略）===
                    # 1. MCP 即時儲存的題目（stream 中已偵測到 question_id）
                    # 2. 從 AI 回應中提取 JSON 題目（新增）
                    # 3. 從 AI 回應中解析 Markdown 題目（舊有後備）
                    all_questions = list(saved_questions)  # MCP 已儲存的
                    mcp_saved_ids = {q.get("id") for q in saved_questions}

                    # 從 AI 完整回應中提取 JSON 格式題目
                    extracted = extract_questions_from_response(full_response)
                    for eq in extracted:
                        # 避免與 MCP 已儲存的重複
                        if eq.get("id") not in mcp_saved_ids:
                            all_questions.append(eq)

                    if all_questions and selected_doc_ids:
                        from src.application.services.textbook_generation_service import get_textbook_generation_service

                        all_questions = get_textbook_generation_service().enrich_generated_questions(
                            all_questions,
                            selected_doc_ids=selected_doc_ids,
                            selected_sections=selected_section_details,
                            preview_only=preview_only_mode,
                        )

                    st.session_state.generated_questions = all_questions
                    st.session_state.generated_questions_auto_saved = False
                    st.session_state.last_generation_response = full_response

                    logger.info(
                        "ui_generation_completed",
                        provider=provider_name,
                        mcp_saved=len(saved_questions),
                        json_extracted=len(extracted),
                        total=len(all_questions),
                    )

                    # 完成訊息
                    if all_questions:
                        autosaved_count = autosave_generated_questions_to_drafts(all_questions)
                        if autosaved_count:
                            invalidate_draft_caches()
                        st.session_state.generated_questions_auto_saved = autosaved_count > 0
                        formal_ready_count = sum(1 for question in all_questions if question_formal_save_ready(question))
                        preview_only_count = sum(1 for question in all_questions if question.get("preview_only"))
                        generation_ui.progress_placeholder.success(
                            f"✅ 生成完成！共提取 {len(all_questions)} 題"
                            f"（MCP 即存: {len(saved_questions)}, JSON 提取: {len(extracted)}）"
                        )
                        if autosaved_count:
                            st.success(f"本批生成結果已同步到題庫管理 {autosaved_count} 題。")
                        if preview_only_count:
                            st.info(f"其中 {preview_only_count} 題已標記為 preview-only，請到題庫管理審閱。")
                        elif formal_ready_count < len(all_questions):
                            st.warning(
                                f"其中 {len(all_questions) - formal_ready_count} 題尚未通過 formal-save gate，請先補 evidence pack，或到題庫管理整理。"
                            )
                        generation_ui.status_container.update(
                            label=f"✅ 生成完成，共 {len(all_questions)} 題",
                            state="complete",
                            expanded=False,
                        )
                    else:
                        st.session_state.generated_questions_auto_saved = False
                        generation_ui.progress_placeholder.warning("⚠️ 生成完成，但未偵測到題目。")
                        generation_ui.status_container.update(
                            label="⚠️ 生成完成，但未偵測到題目",
                            state="error",
                            expanded=True,
                        )
                        with st.expander("🔍 除錯資訊"):
                            st.markdown("**可能原因：**")
                            st.markdown("1. AI 沒有以 JSON 格式輸出題目")
                            st.markdown("2. AI 輸出了題目，但格式不符合目前的 JSON 提取規則")
                            st.markdown("3. Agent 或 MCP 工具鏈在查來源 / 讀教材時中途失敗")
                            st.markdown("---")
                            st.markdown("**完整輸出：**")
                            st.code(full_response[-5000:], language="text")

            # === 題目審閱表單（生成後或從 session state 讀取）===
            if is_e2e_test_mode():
                with st.container(border=True):
                    st.caption("🧪 E2E 教材審閱測試資料")
                    seed_col1, seed_col2, seed_col3 = st.columns(3)
                    with seed_col1:
                        if st.button("🧪 載入教材 preview-only", width="stretch", key="e2e_textbook_preview"):
                            preview_questions = build_e2e_textbook_review_questions("preview")
                            st.session_state.generated_questions = preview_questions
                            autosaved_count = autosave_generated_questions_to_drafts(preview_questions)
                            if autosaved_count:
                                invalidate_draft_caches()
                            st.session_state.generated_questions_auto_saved = autosaved_count > 0
                            st.session_state.last_generation_response = "E2E preview-only textbook review payload"
                            st.rerun()
                    with seed_col2:
                        if st.button("🧪 載入教材 formal-save", width="stretch", key="e2e_textbook_formal"):
                            formal_questions = build_e2e_textbook_review_questions("formal")
                            st.session_state.generated_questions = formal_questions
                            autosaved_count = autosave_generated_questions_to_drafts(formal_questions)
                            if autosaved_count:
                                invalidate_draft_caches()
                            st.session_state.generated_questions_auto_saved = autosaved_count > 0
                            st.session_state.last_generation_response = "E2E formal-save textbook review payload"
                            st.rerun()
                    with seed_col3:
                        if st.button("🧪 清空教材測試資料", width="stretch", key="e2e_textbook_clear"):
                            st.session_state.generated_questions = []
                            st.session_state.generated_questions_auto_saved = False
                            st.session_state.last_generation_response = ""
                            st.rerun()

            if st.session_state.generated_questions:
                render_question_review_form(
                    st.session_state.generated_questions,
                    navigate_to=navigate_to,
                    auto_saved_to_drafts=bool(st.session_state.get("generated_questions_auto_saved")),
                    question_context_callback=set_chat_question_context,
                )

                # 顯示操作按鈕
                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 再生成一批", width="stretch", key="review_regenerate_batch"):
                        st.session_state.generated_questions = []
                        st.session_state.generated_questions_auto_saved = False
                        st.rerun()
                with col2:
                    if st.button("✍️ 立即練習", width="stretch", key="review_start_practice"):
                        qs = st.session_state.generated_questions
                        st.session_state.pending_generated_review_practice = True
                        start_practice_session(
                            qs.copy(),
                            {
                                "source_type": PRACTICE_SOURCE_GENERATED,
                                "label": "生成結果",
                            },
                        )
                        navigate_to_without_query_sync("✍️ 作答練習")
                        st.rerun()

                # 原始 AI 輸出（可展開）
                if st.session_state.get("last_generation_response"):
                    with st.expander("🤖 原始 AI 輸出"):
                        st.code(
                            st.session_state.last_generation_response[-5000:],
                            language="text",
                        )
            else:
                render_empty_state(
                    "等待生成結果",
                    "先設定教材與生成模式。待審、QA 與正式入庫會在題庫管理完成。",
                )

    elif page == "🗃️ 草稿箱":
        st.info("草稿箱已整合到題庫管理頁面，請改在那裡進行待審、QA 與正式入庫。")
        navigate_to("📚 題庫管理")
        st.rerun()

    elif page == "✍️ 作答練習":
        # ===== 作答練習頁面 =====
        EXAM_TRACK_OPTIONS = ["全部", "ite", "pgy", "clerk", "specialist", "board", "custom"]
        EXAM_TRACK_LABELS = {
            "全部": "全部",
            "ite": "ITE",
            "pgy": "PGY",
            "clerk": "Clerk",
            "specialist": "專科",
            "board": "國考/甄審",
            "custom": "自訂",
        }

        all_repo_questions = load_questions()
        past_exam_catalog = load_past_exam_catalog(limit=50)
        past_exam_catalog_map = {entry["id"]: entry for entry in past_exam_catalog}
        render_page_hero(
            "作答練習",
            "從一般題庫或指定考古題快速抽題、作答、看詳解；適合做短回合複習與錯題檢查。",
            [
                f"一般題庫 {len(all_repo_questions)} 題",
                f"歷屆題庫 {content_stats['past_exam_question_count']} 題",
                f"已審查 {content_stats['validated']} 題",
                "提交後即時計分",
            ],
        )

        # 設定區
        with st.expander("📋 練習設定", expanded=not st.session_state.practice_questions):
            practice_source = st.selectbox(
                "題目來源",
                ["一般題庫", "考古題模式"],
                index=0,
                help="可從正式題庫抽題，或依年份區間混抽多份考古題。",
            )

            selected_past_exam_ids: list[str] = []
            selected_year_start: int | None = None
            selected_year_end: int | None = None
            practice_mode = "一般題庫"
            practice_source_questions = all_repo_questions
            source_uses_general_bank_filters = practice_source == "一般題庫"

            if practice_source == "考古題模式":
                practice_source_questions = []
                if past_exam_catalog:
                    practice_mode = st.selectbox(
                        "練習方式",
                        ["多份混抽", "單份考卷"],
                        index=0,
                        help="多份混抽會把年份區間內多份考卷併成同一個題池；單份考卷則維持單一考卷練習。",
                    )

                    available_years = sorted(
                        {
                            year
                            for entry in past_exam_catalog
                            for year in [_safe_year_value(entry.get("exam_year"))]
                            if year is not None
                        }
                    )
                    if available_years:
                        year_col1, year_col2 = st.columns(2)
                        with year_col1:
                            selected_year_start = st.selectbox("起始年度", options=available_years, index=0)
                        with year_col2:
                            selected_year_end = st.selectbox(
                                "結束年度",
                                options=available_years,
                                index=len(available_years) - 1,
                            )

                    year_start = (
                        min(selected_year_start, selected_year_end)
                        if selected_year_start is not None and selected_year_end is not None
                        else None
                    )
                    year_end = (
                        max(selected_year_start, selected_year_end)
                        if selected_year_start is not None and selected_year_end is not None
                        else None
                    )

                    filtered_past_exams = [
                        entry
                        for entry in past_exam_catalog
                        if year_start is None
                        or year_end is None
                        or (year_start <= int(entry.get("exam_year") or 0) <= year_end)
                    ]

                    if not filtered_past_exams:
                        st.info("目前指定的年份區間沒有可用考卷，請放寬年份範圍。")
                    elif practice_mode == "單份考卷":
                        selected_past_exam_id = st.selectbox(
                            "選擇考古題",
                            options=[entry["id"] for entry in filtered_past_exams],
                            format_func=lambda exam_id: format_past_exam_catalog_label(past_exam_catalog_map[exam_id]),
                            help="從年份區間內挑一份考卷來做隨機或順序練習。",
                        )
                        selected_past_exam_ids = [selected_past_exam_id] if selected_past_exam_id else []
                        practice_source_questions = load_past_exam_question_pool(selected_past_exam_ids)
                        selected_exam = past_exam_catalog_map.get(selected_past_exam_id, {})
                        st.caption(
                            f"目前選用 {selected_exam.get('exam_year', '-') } 年 {selected_exam.get('exam_name', '-') }，"
                            f"共 {len(practice_source_questions)} 題。"
                        )
                    else:
                        default_exam_ids = [entry["id"] for entry in filtered_past_exams]
                        selected_past_exam_ids = st.multiselect(
                            "納入考卷",
                            options=default_exam_ids,
                            default=default_exam_ids,
                            format_func=lambda exam_id: format_past_exam_catalog_label(past_exam_catalog_map[exam_id]),
                            help="可從年份區間內再細挑多份考卷一起混抽。",
                        )
                        if selected_past_exam_ids:
                            practice_source_questions = load_past_exam_question_pool(selected_past_exam_ids)
                            st.caption(
                                f"目前納入 {len(selected_past_exam_ids)} 份考卷，"
                                f"共 {len(practice_source_questions)} 題可抽。"
                            )
                        else:
                            st.warning("請至少選擇一份考卷。")
                else:
                    practice_source_questions = []
                    st.info("目前尚未匯入考古題，請先到題庫管理匯入歷屆考卷。")

            practice_topics_options = sorted(
                {topic for q in practice_source_questions for topic in q.get("topics", []) if topic}
            )
            col1, col2 = st.columns(2)

            with col1:
                practice_count = st.number_input(
                    "題數",
                    min_value=1,
                    max_value=50,
                    value=10,
                )

                practice_difficulty = st.selectbox(
                    "難度篩選",
                    ["全部", "簡單", "中等", "困難"],
                    index=0,
                )
                practice_topics = st.multiselect(
                    "主題篩選",
                    practice_topics_options,
                    default=[],
                    help="可多選；留空表示不限主題。",
                )

            with col2:
                practice_validated_only = st.checkbox(
                    f"✅ 只用已審查題目（目前 {content_stats['validated']} 題）",
                    value=False,
                    help="勾選後只從已通過審查的題目中選題",
                    disabled=not source_uses_general_bank_filters or content_stats["validated"] == 0,
                )
                if not source_uses_general_bank_filters:
                    st.caption("考古題練習不套用審查狀態與考試類型篩選。")
                elif content_stats["validated"] == 0:
                    st.caption("目前沒有已審查題目，因此先停用這個篩選。")
                practice_exam_track = st.selectbox(
                    "考試類型",
                    EXAM_TRACK_OPTIONS,
                    format_func=lambda x: EXAM_TRACK_LABELS.get(x, x) or x,
                    index=0,
                    help="依考試類型篩選（ITE / PGY / Clerk 等）",
                    disabled=not source_uses_general_bank_filters,
                )
                practice_random = st.checkbox("隨機順序", value=True)
                st.caption("建議先用主題篩選做小批次訓練，再用隨機順序做混合回顧。")

            if st.button("🎯 開始練習", width="stretch", type="primary"):
                if source_uses_general_bank_filters:
                    # 載入並篩選題目（先用 DB 層篩 validated_only + exam_track）
                    et = practice_exam_track if practice_exam_track != "全部" else None
                    all_questions = load_questions(validated_only=practice_validated_only, exam_track=et)
                    practice_context = {
                        "source_type": PRACTICE_SOURCE_GENERAL,
                        "label": "一般題庫",
                    }
                else:
                    year_start = (
                        min(selected_year_start, selected_year_end)
                        if selected_year_start is not None and selected_year_end is not None
                        else None
                    )
                    year_end = (
                        max(selected_year_start, selected_year_end)
                        if selected_year_start is not None and selected_year_end is not None
                        else None
                    )

                    if not selected_past_exam_ids:
                        st.warning("請先選擇至少一份考古題。")
                        all_questions = []
                        practice_context = {}
                    else:
                        all_questions = list(practice_source_questions)
                        practice_context = {
                            "source_type": PRACTICE_SOURCE_PAST_EXAM,
                            "label": "考古題模式",
                            "mode": practice_mode,
                            "selected_exam_ids": selected_past_exam_ids,
                            "selected_exam_count": len(selected_past_exam_ids),
                            "selected_exam_labels": [
                                format_past_exam_catalog_label(past_exam_catalog_map[exam_id])
                                for exam_id in selected_past_exam_ids
                                if exam_id in past_exam_catalog_map
                            ],
                            "year_start": year_start,
                            "year_end": year_end,
                        }

                # 難度篩選
                diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
                if practice_difficulty != "全部":
                    diff_filter = diff_map.get(practice_difficulty)
                    all_questions = [q for q in all_questions if q.get("difficulty") == diff_filter]

                if practice_topics:
                    all_questions = [
                        q for q in all_questions if set(practice_topics).intersection(set(q.get("topics", [])))
                    ]

                # 隨機/選取
                if practice_random:
                    random.shuffle(all_questions)

                if not all_questions:
                    st.warning("目前篩選條件沒有可練習題目，請放寬難度、主題或更換題目來源。")
                else:
                    start_practice_session(all_questions[:practice_count], practice_context)
                    st.rerun()

        # 作答區
        if st.session_state.practice_questions:
            questions = st.session_state.practice_questions

            # 進度顯示
            answered = len([a for a in st.session_state.practice_answers.values() if a])
            st.progress(answered / len(questions), text=f"已作答 {answered}/{len(questions)} 題")
            top_col1, top_col2, top_col3 = st.columns(3)
            with top_col1:
                st.metric("本回合題數", len(questions))
            with top_col2:
                st.metric("已作答", answered)
            with top_col3:
                remaining = len(questions) - answered
                st.metric("待完成", remaining)

            # 題目列表
            for i, q in enumerate(questions):
                q_id = get_practice_question_key(q, i)

                with st.container(border=True):
                    st.markdown(f"### 第 {i + 1} 題")
                    if q.get("exam_year") or q.get("question_number"):
                        question_prefix = f"第 {q.get('question_number', '-')} 題" if q.get("question_number") else ""
                        st.caption(f"{q.get('exam_year', '-') } 年 {q.get('exam_name', '考古題')} {question_prefix}".strip())
                    st.markdown(q.get("question_text", ""))
                    render_past_exam_question_assets(q)

                    if st.button("🦞 問龍蝦這題", key=f"practice_chat_{q_id}", width="stretch"):
                        set_chat_question_context(q, "作答練習")

                    # 選項
                    options = q.get("options", [])
                    option_labels = [_build_option_label(j, opt) for j, opt in enumerate(options)]
                    option_count = len(option_labels)
                    allows_multiple = _question_type_allows_multiple(q, option_count=option_count)

                    # 作答
                    current_answer = st.session_state.practice_answers.get(q_id, "")
                    current_letters = _normalize_answer_letters(current_answer, option_count=option_count)

                    if allows_multiple:
                        selected = st.multiselect(
                            f"選擇答案 (題目 {i + 1})",
                            options=option_labels,
                            default=_letters_to_option_labels(current_letters, option_labels),
                            key=f"q_{q_id}",
                            label_visibility="collapsed",
                            disabled=st.session_state.practice_submitted,
                        )
                        selected_letters = _letters_from_option_labels(selected)
                        if selected_letters:
                            st.session_state.practice_answers[q_id] = _format_answer_letters(selected_letters)
                        elif not st.session_state.practice_submitted:
                            st.session_state.practice_answers[q_id] = ""
                    else:
                        current_index = None
                        if current_letters:
                            current_index = ord(current_letters[0]) - 65 if ord(current_letters[0]) - 65 < len(option_labels) else None
                        selected = st.radio(
                            f"選擇答案 (題目 {i + 1})",
                            options=option_labels,
                            index=current_index,
                            key=f"q_{q_id}",
                            label_visibility="collapsed",
                            disabled=st.session_state.practice_submitted,
                        )

                        if selected is not None:
                            selected_letters = _letters_from_option_labels([selected])
                            st.session_state.practice_answers[q_id] = _format_answer_letters(selected_letters)
                        elif not st.session_state.practice_submitted:
                            st.session_state.practice_answers[q_id] = ""

                    # 已提交時顯示結果
                    if st.session_state.practice_submitted:
                        correct_letters = _normalize_answer_letters(q.get("correct_answer", ""), option_count=option_count)
                        user_letters = _normalize_answer_letters(st.session_state.practice_answers.get(q_id, ""), option_count=option_count)
                        user_display = _format_answer_letters(user_letters) or "-"
                        correct_display = _format_answer_letters(correct_letters) or "-"

                        if user_letters == correct_letters:
                            st.success(f"✅ 正確！答案：{correct_display}")
                        else:
                            st.error(f"❌ 錯誤！您的答案：{user_display}，正確答案：{correct_display}")

                        # 詳解按鈕
                        if st.button("📖 查看詳解", key=f"exp_{q_id}"):
                            st.session_state.show_explanations[q_id] = not st.session_state.show_explanations.get(
                                q_id, False
                            )

                        if st.session_state.show_explanations.get(q_id, False):
                            st.info(q.get("explanation", "暫無詳解"))

                            # 來源資訊
                            source = q.get("source") or {}
                            if source:
                                render_source_info(source, expanded=False)

            # 提交按鈕
            if not st.session_state.practice_submitted:
                practice_context = st.session_state.get("practice_context", {})
                practice_export_content = build_practice_download_markdown(
                    questions,
                    st.session_state.practice_answers,
                    practice_context,
                )
                practice_export_filename = build_practice_download_filename(practice_context)

                col1, col2, col3 = st.columns([1, 1, 1])
                with col2:
                    if st.button("📤 提交答案", width="stretch", type="primary"):
                        st.session_state.practice_submitted = True
                        st.rerun()
                with col3:
                    st.download_button(
                        "⬇️ 下載題目＋答案詳解",
                        data=practice_export_content,
                        file_name=practice_export_filename,
                        mime="text/markdown",
                        width="stretch",
                    )
            else:
                practice_context = st.session_state.get("practice_context", {})
                practice_result = summarize_practice_results(questions, st.session_state.practice_answers)
                practice_export_content = build_practice_download_markdown(
                    questions,
                    st.session_state.practice_answers,
                    practice_context,
                    practice_result,
                )
                practice_export_filename = build_practice_download_filename(practice_context)
                correct_count = practice_result["correct_count"]
                score = practice_result["score"]
                st.success(f"🎉 本次成績：{correct_count}/{len(questions)} 題 ({score:.1f}%)")

                if practice_context.get("source_type") == PRACTICE_SOURCE_PAST_EXAM:
                    result_rows = practice_result["result_rows"]
                    review_rows = practice_result["review_rows"]
                    covered_exam_count = len({row["exam_label"] for row in result_rows})
                    year_start = practice_context.get("year_start")
                    year_end = practice_context.get("year_end")
                    year_range_text = (
                        f"{year_start}-{year_end} 年"
                        if year_start is not None and year_end is not None
                        else "未限定年份"
                    )

                    st.markdown("#### 考古題模式統計")
                    st.caption(
                        f"來源範圍：{year_range_text}；{practice_context.get('mode', '多份混抽')}；"
                        f"涵蓋 {covered_exam_count} 份考卷，已作答 {practice_result['answered_count']} / {practice_result['total_questions']} 題。"
                    )

                    stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)
                    with stats_col1:
                        st.metric("答對題", practice_result["correct_count"])
                    with stats_col2:
                        st.metric("答錯題", practice_result["incorrect_count"])
                    with stats_col3:
                        st.metric("未作答", practice_result["unanswered_count"])
                    with stats_col4:
                        st.metric("已作答命中率", f"{practice_result['answered_accuracy']:.1f}%")

                    year_rows = build_practice_breakdown_rows(
                        result_rows,
                        group_key="exam_year",
                        label="年度",
                        numeric_sort_desc=True,
                    )
                    exam_rows = build_practice_breakdown_rows(result_rows, group_key="exam_label", label="考卷")
                    pattern_rows = build_practice_breakdown_rows(result_rows, group_key="pattern_label", label="題型")
                    weak_topic_rows = build_practice_weak_topic_rows(result_rows)

                    stats_sections = ["year", "exam", "pattern", "review"]
                    stats_labels = {
                        "year": "年度表現",
                        "exam": "考卷表現",
                        "pattern": "題型與主題",
                        "review": f"錯題回顧 ({len(review_rows)})",
                    }
                    try:
                        selected_stats_section = st.radio(
                            "考古題統計視圖",
                            options=stats_sections,
                            format_func=lambda section: stats_labels.get(section, section),
                            key="past_exam_practice_stats_section",
                            horizontal=True,
                            label_visibility="collapsed",
                        )
                    except TypeError:
                        selected_stats_section = st.radio(
                            "考古題統計視圖",
                            options=stats_sections,
                            format_func=lambda section: stats_labels.get(section, section),
                            key="past_exam_practice_stats_section",
                            label_visibility="collapsed",
                        )

                    if selected_stats_section == "year":
                        st.dataframe(year_rows, width="stretch", hide_index=True)
                    elif selected_stats_section == "exam":
                        st.dataframe(exam_rows, width="stretch", hide_index=True)
                    elif selected_stats_section == "pattern":
                        pattern_col1, pattern_col2 = st.columns(2)
                        with pattern_col1:
                            st.dataframe(pattern_rows, width="stretch", hide_index=True)
                        with pattern_col2:
                            if weak_topic_rows:
                                st.dataframe(weak_topic_rows, width="stretch", hide_index=True)
                            else:
                                st.success("本回合沒有錯題，主題弱點暫時為空。")
                    else:
                        if not review_rows:
                            st.success("本回合全部答對，沒有可回顧的錯題。")
                        else:
                            for row in review_rows:
                                with st.container(border=True):
                                    st.markdown(f"##### {row['exam_label']} 第 {row['question_number']} 題")
                                    st.markdown(row["question_text"])
                                    if row["is_answered"]:
                                        st.error(f"你的答案：{row['user_answer']}；正確答案：{row['correct_answer']}")
                                    else:
                                        st.warning(f"未作答；正確答案：{row['correct_answer']}")

                                    meta_parts = []
                                    if row.get("pattern_label") and row["pattern_label"] != "未分類":
                                        meta_parts.append(f"題型：{row['pattern_label']}")
                                    if row.get("topics"):
                                        meta_parts.append(f"主題：{', '.join(row['topics'])}")
                                    if row.get("source_page"):
                                        meta_parts.append(f"來源頁碼：p.{row['source_page']}")
                                    if meta_parts:
                                        st.caption("｜".join(meta_parts))

                                    render_past_exam_question_assets(row)

                                    if row.get("explanation"):
                                        st.info(row["explanation"])

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("🔄 重新練習", width="stretch"):
                        start_practice_session(questions, practice_context)
                        st.rerun()
                with col2:
                    if st.button("📝 新的練習", width="stretch"):
                        clear_practice_session()
                        st.rerun()
                with col3:
                    st.download_button(
                        "⬇️ 下載題目＋答案詳解",
                        data=practice_export_content,
                        file_name=practice_export_filename,
                        mime="text/markdown",
                        width="stretch",
                    )
        else:
            render_empty_state("尚未開始練習", "先選擇題數、難度或主題，再開始一輪作答。")

    elif page == "📚 題庫管理":
        # ===== 題庫管理頁面 =====
        EXAM_TRACK_OPTIONS_BANK = ["全部", "ite", "pgy", "clerk", "specialist", "board", "custom"]
        EXAM_TRACK_LABELS_BANK = {
            "全部": "全部",
            "ite": "ITE",
            "pgy": "PGY",
            "clerk": "Clerk",
            "specialist": "專科",
            "board": "國考/甄審",
            "custom": "自訂",
        }

        questions = load_questions()
        past_exam_catalog = load_past_exam_catalog(limit=30)
        draft_stats = get_draft_stats()
        all_topics = sorted({topic for q in questions for topic in q.get("topics", [])})
        render_page_hero(
            "題庫管理",
            "搜尋、篩選與抽查題庫內容，並在下方處理待審草稿、QA 與正式入庫。",
            [
                f"一般題庫 {len(questions)} 題",
                f"歷屆題庫 {content_stats['past_exam_question_count']} 題",
                f"待審草稿 {draft_stats.get('draft', 0)} 題",
            ],
        )

        # 篩選區
        with st.container(border=True):
            filter_col1, filter_col2, filter_col3 = st.columns([1.3, 1, 1.2])
            with filter_col1:
                search_query = st.text_input("搜尋題目 / 詳解", placeholder="輸入關鍵字，例如 remimazolam")
            with filter_col2:
                bank_difficulty = st.selectbox("難度", ["全部", "easy", "medium", "hard"], index=0, key="bank_diff")
            with filter_col3:
                bank_topics = st.multiselect("主題", all_topics, default=[], key="bank_topics")

            filter_col4, filter_col5, filter_col6 = st.columns([1, 1, 1])
            with filter_col4:
                bank_validated_only = st.checkbox("✅ 只看已審查", value=False, key="bank_validated")
            with filter_col5:
                bank_exam_track = st.selectbox(
                    "考試類型",
                    EXAM_TRACK_OPTIONS_BANK,
                    format_func=lambda x: EXAM_TRACK_LABELS_BANK.get(x, x) or x,
                    index=0,
                    key="bank_exam_track",
                )
            with filter_col6:
                if st.button("🔄 刷新題庫", width="stretch"):
                    st.rerun()

        # 依 DB 篩選
        et_bank = bank_exam_track if bank_exam_track != "全部" else None
        base_filtered_questions = load_questions(validated_only=False, exam_track=et_bank)
        if search_query:
            query = search_query.strip().lower()
            base_filtered_questions = [
                q
                for q in base_filtered_questions
                if query in q.get("question_text", "").lower() or query in q.get("explanation", "").lower()
            ]
        if bank_difficulty != "全部":
            base_filtered_questions = [q for q in base_filtered_questions if q.get("difficulty") == bank_difficulty]
        if bank_topics:
            base_filtered_questions = [
                q for q in base_filtered_questions if set(bank_topics).intersection(set(q.get("topics", [])))
            ]

        filtered_questions = (
            [q for q in base_filtered_questions if q.get("is_validated")] if bank_validated_only else base_filtered_questions
        )
        pending_questions = [q for q in base_filtered_questions if not q.get("is_validated")]
        bank_sections = ["general", "history", "pending", "drafts"]
        bank_section_labels = {
            "general": f"一般題庫 ({len(filtered_questions)})",
            "history": f"歷屆題庫 ({content_stats['past_exam_question_count']})",
            "pending": f"待審題目 ({len(pending_questions)})",
            "drafts": f"待審草稿 ({draft_stats.get('draft', 0)})",
        }
        try:
            selected_bank_section = st.radio(
                "題庫分頁",
                options=bank_sections,
                format_func=lambda section: bank_section_labels.get(section, section),
                key="bank_active_section",
                horizontal=True,
                label_visibility="collapsed",
            )
        except TypeError:
            selected_bank_section = st.radio(
                "題庫分頁",
                options=bank_sections,
                format_func=lambda section: bank_section_labels.get(section, section),
                key="bank_active_section",
                label_visibility="collapsed",
            )

        if selected_bank_section == "general":
            summary_col1, summary_col2 = st.columns([1, 1])
            with summary_col1:
                st.caption(f"顯示 {len(filtered_questions)} / {len(questions)} 題（一般題庫）")
            with summary_col2:
                if filtered_questions and st.button(
                    "✍️ 用目前篩選結果練習",
                    width="stretch",
                    key="bank_filtered_practice",
                ):
                    queue_practice_session(
                        filtered_questions[:10],
                        {
                            "source_type": PRACTICE_SOURCE_GENERAL,
                            "label": "題庫篩選結果",
                        },
                    )
                    st.rerun()

            if not questions:
                st.info("📭 題庫空空如也，請先生成考題！")
            elif not filtered_questions:
                render_empty_state("沒有符合條件的題目", "試著放寬關鍵字、難度或主題篩選。")
            else:
                st.dataframe(build_question_scan_rows(filtered_questions), width="stretch", hide_index=True)
                show_general_review_panel = st.checkbox(
                    "顯示一般題庫單題審閱面板",
                    value=False,
                    key="bank_general_show_review_panel",
                )
                if not show_general_review_panel:
                    st.caption("目前只顯示掃描表格；需要逐題審閱時再開啟單題面板。")
                else:
                    detail_limit = int(
                        st.number_input(
                            "一般題庫審閱面板載入數",
                            min_value=1,
                            max_value=100,
                            value=min(12, len(filtered_questions)),
                            step=1,
                            key="bank_general_detail_limit",
                        )
                    )
                    detail_questions = filtered_questions[:detail_limit]
                    st.caption(
                        f"先用表格快速掃描，再展開單題做審查與修正（目前載入前 {len(detail_questions)} 題）。"
                    )
                    for i, question in enumerate(detail_questions, start=1):
                        render_question_review_expander(question, i, key_prefix="bank_all")
                    if len(filtered_questions) > detail_limit:
                        st.info(
                            f"尚有 {len(filtered_questions) - detail_limit} 題未展開。可調高載入數，或先縮小搜尋條件。"
                        )

        elif selected_bank_section == "history":
            st.caption("歷屆題庫與一般題庫分開存放；這裡列的是已匯入的考古題與考卷。")
            if not past_exam_catalog:
                render_empty_state("尚未匯入歷屆考卷", "請先執行歷屆考題匯入流程。")
            else:
                explanation_service = get_past_exam_explanation_service()
                st.dataframe(build_past_exam_scan_rows(past_exam_catalog), width="stretch", hide_index=True)
                selected_past_exam_id = st.selectbox(
                    "檢視歷屆考卷",
                    options=[exam["id"] for exam in past_exam_catalog],
                    format_func=lambda exam_id: next(
                        (
                            f"{exam['exam_year']}｜{exam['exam_name']}"
                            for exam in past_exam_catalog
                            if exam["id"] == exam_id
                        ),
                        exam_id,
                    ),
                    key="selected_past_exam_id",
                ) or past_exam_catalog[0]["id"]
                selected_past_exam = next(
                    (exam for exam in past_exam_catalog if exam["id"] == selected_past_exam_id),
                    past_exam_catalog[0],
                )
                past_exam_questions = load_past_exam_questions(selected_past_exam_id)
                explanation_ready_count = sum(
                    1 for question in past_exam_questions if str(question.get("explanation") or "").strip()
                )
                missing_explanation_count = len(past_exam_questions) - explanation_ready_count

                status_col1, status_col2, status_col3 = st.columns(3)
                with status_col1:
                    st.metric("本卷題數", len(past_exam_questions))
                with status_col2:
                    st.metric("已有詳解", explanation_ready_count)
                with status_col3:
                    st.metric("待補詳解", missing_explanation_count)

                filter_col1, filter_col2, filter_col3 = st.columns([1.5, 1, 1])
                with filter_col1:
                    past_exam_query = st.text_input(
                        "搜尋歷屆題目",
                        placeholder="輸入關鍵字，例如 malignant hyperthermia",
                        key="past_exam_query",
                    )
                with filter_col2:
                    past_exam_missing_only = st.checkbox(
                        "只看缺詳解",
                        value=False,
                        key="past_exam_missing_only",
                    )
                with filter_col3:
                    past_exam_batch_limit = st.number_input(
                        "批次補寫題數",
                        min_value=1,
                        max_value=10,
                        value=3,
                        step=1,
                        key="past_exam_batch_limit",
                    )

                filtered_past_exam_questions = list(past_exam_questions)
                if past_exam_query:
                    query = past_exam_query.strip().lower()
                    filtered_past_exam_questions = [
                        question
                        for question in filtered_past_exam_questions
                        if query in question.get("question_text", "").lower()
                        or query in str(question.get("explanation") or "").lower()
                    ]
                if past_exam_missing_only:
                    filtered_past_exam_questions = [
                        question
                        for question in filtered_past_exam_questions
                        if not str(question.get("explanation") or "").strip()
                    ]

                provider_for_explanation = (
                    st.session_state.agent_provider if st.session_state.agent_available else None
                )
                explanation_available, explanation_reason = explanation_service.get_generation_availability(
                    provider=provider_for_explanation
                )

                action_col1, action_col2 = st.columns([1, 1.2])
                with action_col1:
                    if st.button(
                        "🤖 批次補本卷缺詳解",
                        width="stretch",
                        key=f"past_exam_batch_generate_{selected_past_exam_id}",
                        disabled=not explanation_available or not filtered_past_exam_questions,
                    ):
                        with st.spinner("正在生成並寫回考古題詳解..."):
                            batch_result = explanation_service.generate_and_save_missing_explanations(
                                filtered_past_exam_questions,
                                provider=provider_for_explanation,
                                limit=int(past_exam_batch_limit),
                            )
                        invalidate_past_exam_caches()
                        for item in batch_result["generated"]:
                            update_question_explanation_in_place(
                                past_exam_questions,
                                str(item.get("question_id") or ""),
                                str(item.get("explanation") or ""),
                            )
                            update_question_explanation_in_place(
                                filtered_past_exam_questions,
                                str(item.get("question_id") or ""),
                                str(item.get("explanation") or ""),
                            )

                        if batch_result["generated"]:
                            st.success(f"已補寫並存檔 {len(batch_result['generated'])} 題詳解。")
                        if batch_result["errors"]:
                            st.warning(f"有 {len(batch_result['errors'])} 題補寫失敗，請查看 log 或稍後重試。")

                        if past_exam_missing_only:
                            filtered_past_exam_questions = [
                                question
                                for question in filtered_past_exam_questions
                                if not str(question.get("explanation") or "").strip()
                            ]
                with action_col2:
                    if explanation_available:
                        st.caption(f"詳解生成可用：{explanation_reason}")
                    else:
                        st.warning(f"目前無法生成詳解：{explanation_reason}")

                st.caption(
                    f"{selected_past_exam['exam_name']}：顯示 {len(filtered_past_exam_questions)} / "
                    f"{selected_past_exam['total_questions']} 題"
                )
                st.dataframe(
                    [
                        {
                            "題號": question.get("question_number", 0),
                            "題目": (
                                question.get("question_text", "")[:56].rstrip() + "..."
                                if len(question.get("question_text", "")) > 56
                                else question.get("question_text", "")
                            ),
                            "難度": question.get("difficulty", "medium"),
                            "答案": _format_answer_letters(_normalize_answer_letters(question.get("correct_answer", ""), len(question.get("options") or []))) or "-",
                            "詳解": "已有" if str(question.get("explanation") or "").strip() else "待補",
                            "頁碼": question.get("source_page") or "-",
                        }
                        for question in filtered_past_exam_questions
                    ],
                    width="stretch",
                    hide_index=True,
                )

                if not filtered_past_exam_questions:
                    render_empty_state("目前沒有符合條件的歷屆題目", "試著放寬搜尋條件，或取消「只看缺詳解」。")
                else:
                    selected_past_exam_question_id = st.selectbox(
                        "檢視歷屆題目",
                        options=[question["id"] for question in filtered_past_exam_questions],
                        format_func=lambda question_id: next(
                            (
                                f"第 {question['question_number']} 題｜{question.get('question_text', '')[:48]}"
                                for question in filtered_past_exam_questions
                                if question["id"] == question_id
                            ),
                            question_id,
                        ),
                        key=f"selected_past_exam_question_{selected_past_exam_id}",
                    )
                    selected_past_exam_question = next(
                        (
                            question
                            for question in filtered_past_exam_questions
                            if question["id"] == selected_past_exam_question_id
                        ),
                        filtered_past_exam_questions[0],
                    )
                    evidence_state_key = f"past_exam_context_evidence_{selected_past_exam_question['id']}"
                    evidence_state = st.session_state.get(evidence_state_key) or {}
                    reference_matches = (
                        list(evidence_state.get("reference_matches") or [])
                        if isinstance(evidence_state, dict)
                        else []
                    )
                    textbook_evidence = (
                        dict(evidence_state.get("textbook_evidence") or {})
                        if isinstance(evidence_state, dict)
                        else {}
                    ) or _empty_textbook_evidence_pack("尚未載入教材定位")

                    if st.button(
                        "🔎 載入參考脈絡與教材定位",
                        width="stretch",
                        key=f"past_exam_load_context_{selected_past_exam_question['id']}",
                    ):
                        with st.spinner("正在查找參考題與教材定位..."):
                            reference_matches = explanation_service.find_reference_matches(
                                selected_past_exam_question,
                                limit=5,
                            )
                            textbook_evidence = _resolve_textbook_evidence(
                                explanation_service,
                                selected_past_exam_question,
                            )
                        st.session_state[evidence_state_key] = {
                            "reference_matches": reference_matches,
                            "textbook_evidence": textbook_evidence,
                        }

                    with st.container(border=True):
                        st.markdown(
                            f"### 第 {selected_past_exam_question.get('question_number', '-')} 題"
                        )
                        st.caption(
                            f"{selected_past_exam_question.get('exam_year', '-')}"
                            f"｜{selected_past_exam_question.get('exam_name', '考古題')}"
                        )
                        st.markdown(selected_past_exam_question.get("question_text", ""))
                        render_past_exam_question_assets(selected_past_exam_question)

                        st.markdown("**選項**")
                        for option_index, option in enumerate(selected_past_exam_question.get("options", [])):
                            st.markdown(f"- {chr(65 + option_index)}. {option}")

                        meta_col1, meta_col2, meta_col3 = st.columns(3)
                        with meta_col1:
                            correct_letters = _normalize_answer_letters(
                                selected_past_exam_question.get("correct_answer", "-"),
                                option_count=len(selected_past_exam_question.get("options") or []),
                            )
                            st.markdown(f"**答案:** {_format_answer_letters(correct_letters) or '-'}")
                        with meta_col2:
                            st.markdown(f"**難度:** {selected_past_exam_question.get('difficulty', 'medium')}")
                        with meta_col3:
                            st.markdown(
                                f"**主題:** {', '.join(selected_past_exam_question.get('topics', [])) or '-'}"
                            )

                        if selected_past_exam_question.get("explanation"):
                            st.info(selected_past_exam_question["explanation"])
                        else:
                            st.warning("這題目前尚無詳解。")

                        detail_col1, detail_col2, detail_col3 = st.columns([1, 1, 1])
                        with detail_col1:
                            if st.button(
                                "🤖 產生並存入這題詳解",
                                width="stretch",
                                key=f"past_exam_generate_one_{selected_past_exam_question['id']}",
                                disabled=not explanation_available,
                            ):
                                with st.spinner("正在生成這題詳解..."):
                                    generated_result = explanation_service.generate_and_save_explanation(
                                        selected_past_exam_question,
                                        provider=provider_for_explanation,
                                    )
                                invalidate_past_exam_caches()
                                textbook_evidence = generated_result.get("textbook_evidence") or textbook_evidence
                                update_question_explanation_in_place(
                                    past_exam_questions,
                                    str(selected_past_exam_question["id"]),
                                    generated_result["explanation"],
                                )
                                update_question_explanation_in_place(
                                    filtered_past_exam_questions,
                                    str(selected_past_exam_question["id"]),
                                    generated_result["explanation"],
                                )
                                selected_past_exam_question["explanation"] = generated_result["explanation"]
                                st.success("詳解已生成並寫回資料庫。")
                        with detail_col2:
                            if st.button(
                                "✍️ 練這份考卷",
                                width="stretch",
                                key=f"past_exam_practice_{selected_past_exam_id}",
                            ):
                                queue_practice_session(
                                    load_past_exam_question_pool([selected_past_exam_id]),
                                    {
                                        "source_type": PRACTICE_SOURCE_PAST_EXAM,
                                        "label": "歷屆考卷",
                                        "mode": "單份考卷",
                                        "selected_exam_ids": [selected_past_exam_id],
                                        "selected_exam_names": [selected_past_exam.get("exam_name", "考古題")],
                                        "year_start": selected_past_exam.get("exam_year"),
                                        "year_end": selected_past_exam.get("exam_year"),
                                    },
                                )
                                navigate_to_without_query_sync("✍️ 作答練習")
                                st.rerun()
                        with detail_col3:
                            if st.button(
                                "🦞 問龍蝦這題",
                                width="stretch",
                                key=f"past_exam_chat_{selected_past_exam_question['id']}",
                            ):
                                set_chat_question_context(selected_past_exam_question, "歷屆審題")

                        with st.expander(f"🔎 題庫參考脈絡 ({len(reference_matches)})", expanded=False):
                            if not reference_matches:
                                st.caption("目前沒有找到帶詳解的近似題，生成時會主要依題幹、選項與知識點推理。")
                            else:
                                st.dataframe(
                                    [
                                        {
                                            "來源": reference.get("label", ""),
                                            "答案": _format_answer_letters(reference.get("correct_answer", "")),
                                            "主題": ", ".join(reference.get("topics", [])),
                                            "相似度": f"{float(reference.get('score', 0.0)):.2f}",
                                            "題目": _truncate_text(reference.get("question_text", ""), 72),
                                            "詳解摘要": _truncate_text(reference.get("explanation", ""), 120),
                                        }
                                        for reference in reference_matches
                                    ],
                                    width="stretch",
                                    hide_index=True,
                                )

                        textbook_ready = bool(textbook_evidence.get("source_ready"))
                        textbook_source = textbook_evidence.get("source") or {}
                        textbook_locations = []
                        for label, location in (
                            ("題幹", textbook_source.get("stem_source")),
                            ("答案", textbook_source.get("answer_source")),
                        ):
                            if location:
                                textbook_locations.append(
                                    {
                                        "定位": label,
                                        "頁碼": location.get("page"),
                                        "行號": f"L{location.get('line_start')}-{location.get('line_end')}",
                                        "摘錄": _truncate_text(location.get("original_text", ""), 140),
                                    }
                                )
                        for index, location in enumerate(textbook_source.get("explanation_sources", []), start=1):
                            textbook_locations.append(
                                {
                                    "定位": f"詳解依據 {index}",
                                    "頁碼": location.get("page"),
                                    "行號": f"L{location.get('line_start')}-{location.get('line_end')}",
                                    "摘錄": _truncate_text(location.get("original_text", ""), 140),
                                }
                            )

                        with st.expander(
                            f"📚 教材定位 ({'已命中' if textbook_ready else '未命中'})",
                            expanded=False,
                        ):
                            if textbook_ready:
                                st.markdown(
                                    f"**教材:** {textbook_evidence.get('matched_doc_title', '-')}"
                                )
                                st.markdown(
                                    f"**章節:** "
                                    f"{textbook_source.get('chapter', '-')}"
                                    f"｜{textbook_source.get('section', '-')}"
                                )
                                if textbook_locations:
                                    st.dataframe(textbook_locations, width="stretch", hide_index=True)
                            else:
                                st.caption("目前沒有命中可精確引用的教材 block；生成時會明確避免捏造教材定位。")
                                gate_reasons = textbook_evidence.get("gate_reasons", [])
                                if gate_reasons:
                                    st.write("未命中原因：")
                                    for reason in gate_reasons:
                                        st.markdown(f"- {reason}")

        elif selected_bank_section == "pending":
            st.caption("待審題目 = 一般題庫中尚未標記通過的題目。")
            if not pending_questions:
                render_empty_state("目前沒有待審題目", "代表目前篩選結果都已審查，或條件過於嚴格。")
            else:
                st.dataframe(build_question_scan_rows(pending_questions), width="stretch", hide_index=True)
                show_pending_review_panel = st.checkbox(
                    "顯示待審題目單題審閱面板",
                    value=False,
                    key="bank_pending_show_review_panel",
                )
                if not show_pending_review_panel:
                    st.caption("目前只顯示待審掃描表格；需要逐題處理時再開啟單題面板。")
                else:
                    pending_limit = int(
                        st.number_input(
                            "待審題目面板載入數",
                            min_value=1,
                            max_value=100,
                            value=min(12, len(pending_questions)),
                            step=1,
                            key="bank_pending_detail_limit",
                        )
                    )
                    detail_pending = pending_questions[:pending_limit]
                    st.caption(f"目前展開前 {len(detail_pending)} 題待審題目。")
                    for i, question in enumerate(detail_pending, start=1):
                        render_question_review_expander(question, i, key_prefix="bank_pending")
                    if len(pending_questions) > pending_limit:
                        st.info(
                            f"尚有 {len(pending_questions) - pending_limit} 題未展開。可調高載入數，或先縮小篩選條件。"
                        )

        else:
            st.caption("待審草稿區會在這裡處理模板套用、QA、批次編修與正式入庫。")
            render_draft_workspace(show_hero=False)

    elif page == "📋 出題需求":
        # ===== 出題需求 / 補題 backlog =====
        from src.application.services.heartbeat_service import HeartbeatService
        from src.application.services.scope_request_dispatch_service import get_scope_request_dispatch_service
        from src.domain.entities.scope_request import ScopeRequest, ScopeRequestStatus
        from src.infrastructure.persistence.sqlite_scope_request_repo import get_scope_request_repository

        EXAM_TRACK_OPTIONS_SCOPE = ["全部", "ite", "pgy", "clerk", "specialist", "board", "custom"]
        EXAM_TRACK_LABELS_SCOPE = {
            "全部": "全部",
            "ite": "ITE",
            "pgy": "PGY",
            "clerk": "Clerk",
            "specialist": "專科",
            "board": "國考/甄審",
            "custom": "自訂",
        }
        SCOPE_STATUS_OPTIONS = ["全部", "pending", "approved", "in_progress", "fulfilled", "rejected"]
        SCOPE_STATUS_LABELS = {
            "全部": "全部",
            "pending": "待處理",
            "approved": "已核准",
            "in_progress": "補題中",
            "fulfilled": "已完成",
            "rejected": "已駁回",
        }

        scope_repo = get_scope_request_repository()
        heartbeat = HeartbeatService()
        dispatch_service = get_scope_request_dispatch_service()
        heartbeat_summary = heartbeat.get_status_summary()
        scope_stats = heartbeat_summary["scope_requests"]
        repo_mcp_ready = provider_supports_repo_mcp(st.session_state.agent_provider_name, st.session_state.agent_meta)

        render_page_hero(
            "出題需求與補題 Backlog",
            "使用者可提交缺題需求，管理者可核准；除了 heartbeat 寫 job，也可直接派給目前連線的 agent 補題。",
            [
                f"需求 {scope_stats.get('total', 0)} 筆",
                f"待處理 job {heartbeat_summary['jobs']['pending']} 筆",
                f"覆蓋缺口 {heartbeat_summary['coverage_gaps']} 項",
            ],
        )

        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        with metric_col1:
            st.metric("需求總數", scope_stats.get("total", 0))
        with metric_col2:
            open_requests = (
                scope_stats.get("by_status", {}).get("pending", 0)
                + scope_stats.get("by_status", {}).get("approved", 0)
                + scope_stats.get("by_status", {}).get("in_progress", 0)
            )
            st.metric("待處理需求", open_requests)
        with metric_col3:
            st.metric("待執行 Jobs", heartbeat_summary["jobs"]["pending"])
        with metric_col4:
            st.metric("已補題數", scope_stats.get("total_fulfilled", 0))

        with st.container(border=True):
            st.subheader("📝 提交出題需求")
            with st.form("scope_request_form"):
                form_col1, form_col2 = st.columns(2)
                with form_col1:
                    scope_topic = st.text_input("主題 / 標籤", placeholder="例如：惡性高熱")
                    scope_chapter = st.text_input("章節（可選）", placeholder="例如：Chapter 12")
                    scope_difficulty = st.selectbox("期望難度", ["不限", "easy", "medium", "hard"], index=0)
                with form_col2:
                    scope_exam_track = st.selectbox(
                        "考試類型",
                        EXAM_TRACK_OPTIONS_SCOPE,
                        format_func=lambda x: EXAM_TRACK_LABELS_SCOPE.get(x, x) or x,
                        index=0,
                    )
                    scope_target_count = st.number_input("希望補幾題", min_value=1, max_value=30, value=5)
                    scope_requested_by = st.text_input("提出者", value="user")

                scope_reason = st.text_area(
                    "需求原因",
                    placeholder="例如：最近練習發現這個主題題數太少，想補充臨床情境題。",
                    height=100,
                )

                submit_scope = st.form_submit_button("📨 提交需求", width="stretch", type="primary")

            if submit_scope:
                if not scope_topic.strip():
                    st.error("請輸入主題。")
                elif not scope_reason.strip():
                    st.error("請輸入需求原因，方便後台補題。")
                else:
                    request = ScopeRequest(
                        topic=scope_topic.strip(),
                        chapter=scope_chapter.strip() or None,
                        difficulty=None if scope_difficulty == "不限" else scope_difficulty,
                        exam_track=None if scope_exam_track == "全部" else scope_exam_track,
                        reason=scope_reason.strip(),
                        requested_by=scope_requested_by.strip() or "user",
                        target_count=int(scope_target_count),
                    )
                    scope_repo.save(request)
                    invalidate_scope_request_caches()
                    st.success("已建立出題需求。")
                    st.rerun()

        with st.container(border=True):
            st.subheader("🫀 Heartbeat Job 產生")
            hb_col1, hb_col2, hb_col3 = st.columns([1, 1, 1.2])
            with hb_col1:
                hb_max_requests = st.number_input(
                    "單次 job 上限",
                    min_value=1,
                    max_value=20,
                    value=5,
                    key="hb_max_requests",
                )
            with hb_col2:
                if st.button("🔍 Dry Run 分析缺口", width="stretch"):
                    dry_result = heartbeat.run_heartbeat(max_requests=int(hb_max_requests), dry_run=True)
                    st.json(dry_result.to_dict())
            with hb_col3:
                if st.button("📝 產生補題 Jobs", width="stretch", type="primary"):
                    write_result = heartbeat.run_heartbeat(max_requests=int(hb_max_requests), dry_run=False)
                    if write_result.jobs_written:
                        st.success(f"已寫入 {write_result.jobs_written} 個 job 檔案。")
                        st.code("\n".join(write_result.job_paths))
                    else:
                        st.info("這次沒有新增 job，可能是目前沒有缺口，或相同主題已經有 pending job。")

        with st.container(border=True):
            st.subheader("📚 需求列表")
            filter_status = st.selectbox(
                "狀態篩選",
                SCOPE_STATUS_OPTIONS,
                format_func=lambda x: SCOPE_STATUS_LABELS.get(x, x) or x,
                index=0,
            )

            requests = load_scope_requests(status=None if filter_status == "全部" else filter_status)
            if not requests:
                render_empty_state("目前沒有需求", "提交第一筆出題需求後，heartbeat 才會有 backlog 可以轉成 job。")
            else:
                for req in requests:
                    progress = req.get("fulfilled_count", 0) / max(req.get("target_count", 1), 1)
                    title = f"{req.get('topic', '未命名')} · {SCOPE_STATUS_LABELS.get(req.get('status', 'pending'), req.get('status', 'pending'))}"
                    with st.expander(title):
                        badge_parts = [
                            f'<span class="status-chip-good">{SCOPE_STATUS_LABELS.get(req.get("status", "pending"), req.get("status", "pending"))}</span>'
                        ]
                        if req.get("exam_track"):
                            badge_parts.append(
                                f'<span class="status-chip-good">{str(req["exam_track"]).upper()}</span>'
                            )
                        if req.get("difficulty"):
                            badge_parts.append(f'<span class="status-chip-warn">{req["difficulty"]}</span>')
                        st.markdown(" ".join(badge_parts), unsafe_allow_html=True)

                        st.markdown(f"**主題:** {req.get('topic', '')}")
                        if req.get("chapter"):
                            st.markdown(f"**章節:** {req.get('chapter', '')}")
                        st.markdown(f"**提出者:** {req.get('requested_by', 'user')}")
                        st.markdown(f"**需求原因:** {req.get('reason', '')}")
                        st.progress(
                            progress, text=f"已完成 {req.get('fulfilled_count', 0)} / {req.get('target_count', 0)} 題"
                        )

                        admin_note = st.text_input(
                            "管理備註",
                            value=req.get("admin_notes") or "",
                            key=f"scope_admin_note_{req.get('id')}",
                        )

                        action_col1, action_col2, action_col3 = st.columns(3)
                        with action_col1:
                            if st.button("✅ 核准需求", key=f"scope_approve_{req.get('id')}", width="stretch"):
                                scope_repo.update_status(
                                    req["id"],
                                    ScopeRequestStatus.APPROVED,
                                    admin_notes=admin_note or None,
                                )
                                invalidate_scope_request_caches()
                                st.rerun()
                        with action_col2:
                            if st.button("❌ 駁回需求", key=f"scope_reject_{req.get('id')}", width="stretch"):
                                scope_repo.update_status(
                                    req["id"],
                                    ScopeRequestStatus.REJECTED,
                                    admin_notes=admin_note or None,
                                )
                                invalidate_scope_request_caches()
                                st.rerun()
                        with action_col3:
                            if st.button(
                                "🦞 立即派給龍蝦",
                                key=f"scope_dispatch_{req.get('id')}",
                                width="stretch",
                                disabled=(
                                    req.get("status") not in {"approved", "in_progress"}
                                    or not st.session_state.agent_available
                                    or not repo_mcp_ready
                                ),
                            ):
                                with st.spinner("龍蝦補題中..."):
                                    agent_provider = cast(Any, st.session_state.agent_provider)
                                    try:
                                        dispatch_result = dispatch_service.dispatch(req["id"], agent_provider)
                                    except Exception as exc:
                                        logger.exception(
                                            "streamlit_scope_dispatch_failed",
                                            request_id=req.get("id"),
                                            error=str(exc),
                                        )
                                        st.error(f"派工失敗：{exc}")
                                    else:
                                        invalidate_scope_request_caches()
                                        invalidate_question_bank_caches()
                                        if dispatch_result.generated_count > 0:
                                            st.success(
                                                f"龍蝦已寫回 {dispatch_result.generated_count} 題；本次計入需求進度 {dispatch_result.applied_count} 題。"
                                            )
                                        else:
                                            st.warning("龍蝦這次沒有成功寫入題目；詳細摘要已寫入管理備註。")
                                        st.rerun()

                        if req.get("status") not in {"approved", "in_progress"}:
                            st.caption("先核准需求，再直接派給龍蝦補題。")
                        elif not st.session_state.agent_available:
                            st.caption("目前 agent 未連線，暫時不能直接派工。")
                        elif not repo_mcp_ready:
                            st.caption("目前 provider 尚未接通 repo MCP 工具，暫時不能直接派工。")

        pending_jobs = heartbeat.list_jobs(status="pending")
        if pending_jobs:
            with st.container(border=True):
                st.subheader("⏳ Pending Jobs")
                for job in pending_jobs[:10]:
                    st.markdown(f"- {job.get('topic', '')} · 缺 {job.get('deficit', 0)} 題 · {job.get('_path', '')}")

    elif page == "📊 統計":
        # ===== 統計頁面 =====
        render_page_hero(
            "題庫統計",
            "快速掌握一般題庫、歷屆題庫與補題狀態，避免把不同資料層誤看成同一個題庫數字。",
            [
                f"一般題庫 {content_stats['regular_question_count']} 題",
                f"歷屆題庫 {content_stats['past_exam_question_count']} 題",
                f"歷屆考卷 {content_stats['past_exam_count']} 份",
            ],
        )

        stats = content_stats
        heartbeat_summary = get_heartbeat_summary()

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("📝 一般題庫題數", stats["regular_question_count"])
            st.metric("🗂️ 歷屆題目數", stats["past_exam_question_count"])
            st.metric("📚 歷屆考卷數", stats["past_exam_count"])
            st.metric("✅ 已審查一般題", stats["validated"])
            st.caption(f"另有 {stats['generated_exam_count']} 份練習考卷 JSON 檔。")

        with col2:
            st.subheader("一般題庫難度分布")
            diff = stats["difficulty"]
            total = sum(diff.values()) or 1

            st.progress(diff["easy"] / total, text=f"簡單: {diff['easy']} 題")
            st.progress(diff["medium"] / total, text=f"中等: {diff['medium']} 題")
            st.progress(diff["hard"] / total, text=f"困難: {diff['hard']} 題")

        with col3:
            st.subheader("補題狀態")
            st.metric(
                "待處理需求",
                (
                    heartbeat_summary["scope_requests"].get("by_status", {}).get("pending", 0)
                    + heartbeat_summary["scope_requests"].get("by_status", {}).get("approved", 0)
                    + heartbeat_summary["scope_requests"].get("by_status", {}).get("in_progress", 0)
                ),
            )
            st.metric("Pending Jobs", heartbeat_summary["jobs"]["pending"])
            st.metric("覆蓋缺口", heartbeat_summary["coverage_gaps"])

        st.markdown("---")

        top_topics = sorted(stats["by_topic"].items(), key=lambda item: item[1], reverse=True)[:8]
        if top_topics:
            st.subheader("🏷️ 高頻主題")
            topic_max = top_topics[0][1] or 1
            for topic_name, topic_count in top_topics:
                st.progress(topic_count / topic_max, text=f"{topic_name}: {topic_count} 題")

            st.markdown("---")

        top_gaps = heartbeat_summary.get("top_gaps", [])
        if top_gaps:
            st.subheader("🫀 優先補題缺口")
            for gap in top_gaps:
                label = gap["topic"]
                if gap.get("difficulty"):
                    label += f" ({gap['difficulty']})"
                st.markdown(f"- {label}: 尚缺 {gap['deficit']} 題")

            st.markdown("---")

        # 最近生成
        st.subheader("📅 最近生成")
        questions = load_questions()[:5]

        if questions:
            for q in questions:
                st.markdown(f"- {q.get('question_text', '')[:60]}...")
        else:
            st.info("尚無題目")


# ===== 右欄：常駐 Chat =====
with chat_col:
    render_chat_panel(page)


# ===== 底部資訊 =====
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    st.caption(f"對話數: {len(st.session_state.messages)}")
with col2:
    st.caption(f"模型: {st.session_state.agent_model or 'N/A'}")
with col3:
    st.caption(
        f"Agent({st.session_state.agent_provider_name}): {'已連線' if st.session_state.agent_available else '未連線'}"
    )
