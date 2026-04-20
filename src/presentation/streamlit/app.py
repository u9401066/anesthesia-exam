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
import time
from collections import Counter
from pathlib import Path

# 確保專案根目錄在 Python path 中
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import json
import random
import subprocess
import uuid
from datetime import datetime
from typing import Optional

import streamlit as st

from src.infrastructure.agent import AgentProviderConfig, create_agent_provider
from src.infrastructure.logging import configure_logging, get_logger

# 初始化結構化 logging（JSON 寫入 logs/）
LOG_DIR = PROJECT_DIR / "logs"
configure_logging(log_dir=LOG_DIR, level="INFO")
logger = get_logger(__name__)

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

PAGE_OPTIONS = ["📝 生成考題", "🗃️ 草稿箱", "✍️ 作答練習", "📚 題庫管理", "📋 出題需求", "📊 統計"]
PAGE_LABEL_TO_PARAM = {
    "📝 生成考題": "generate",
    "🗃️ 草稿箱": "drafts",
    "✍️ 作答練習": "practice",
    "📚 題庫管理": "library",
    "📋 出題需求": "scope",
    "📊 統計": "stats",
}
PAGE_PARAM_TO_LABEL = {value: key for key, value in PAGE_LABEL_TO_PARAM.items()}

CHAT_QUICK_PROMPTS = [
    "幫我說明這個頁面的最佳操作順序。",
    "幫我檢查目前選題的詳解品質。",
    "請提供一個題目審閱 checklist。",
]

PRACTICE_SOURCE_GENERAL = "general_bank"
PRACTICE_SOURCE_GENERATED = "generated_preview"
PRACTICE_SOURCE_PAST_EXAM = "past_exam"
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


def sync_current_page_from_nav() -> None:
    """Keep page navigation state in one place when the sidebar radio changes."""
    selected_page = st.session_state.get("page_nav")
    if selected_page in PAGE_OPTIONS:
        st.session_state.current_page = selected_page
        sync_query_params_with_page(selected_page)


def navigate_to(page: str) -> None:
    """Programmatically switch pages without fighting the sidebar widget state."""
    if page not in PAGE_OPTIONS:
        return
    st.session_state.current_page = page
    sync_query_params_with_page(page)


def sync_nav_widget_state() -> None:
    """Ensure the sidebar radio reflects the current programmatic page state."""
    current_page = st.session_state.get("current_page")
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


def ensure_review_question_widget_key(question: dict, fallback_index: int) -> str:
    """Attach a stable UI key to generated-review questions across reruns."""
    question_id = str(question.get("id") or "").strip()
    if question_id:
        return question_id

    existing_widget_key = str(question.get("_review_widget_key") or "").strip()
    if existing_widget_key:
        return existing_widget_key

    key_seed = "|".join(
        [
            question.get("question_text", ""),
            json.dumps(question.get("options", []), ensure_ascii=False),
            question.get("explanation", ""),
            str(fallback_index),
        ]
    )
    widget_key = hashlib.sha1(key_seed.encode("utf-8")).hexdigest()[:12]
    question["_review_widget_key"] = widget_key
    return widget_key


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
        user_answer = str(practice_answers.get(question_key, "") or "")
        user_letter = user_answer[0] if user_answer else ""
        correct_answer = str(question.get("correct_answer", "") or "")
        is_answered = bool(user_letter)
        is_correct = is_answered and user_letter == correct_answer

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
                "user_answer": user_letter or "-",
                "correct_answer": correct_answer or "-",
                "is_answered": is_answered,
                "is_correct": is_correct,
                "explanation": question.get("explanation", ""),
                "source_page": question.get("source_page"),
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

            [data-testid="stSidebar"] .block-container {
                padding-top: 1.8rem;
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


def question_formal_save_ready(question: dict) -> bool:
    """判斷題目是否已滿足 formal-save evidence gate。"""
    from src.application.services.textbook_generation_service import get_textbook_generation_service

    return get_textbook_generation_service().question_formal_save_ready(question)


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
                    m = json.load(f)
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
                global_manifest = json.load(f)
            for src in global_manifest.get("sources", []):
                doc_id = src.get("doc_id", "")
                if doc_id and doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    docs.append(enrich_doc_manifest(src))
        except Exception as e:
            logger.warning("manifest_load_error", error=str(e))

    return docs


def load_agent_metadata(provider_name: str = "crush") -> dict:
    """根據 provider 載入對應的模型/MCP/context 設定（供 UI 顯示）"""
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
            meta["model"] = data.get("model")
            meta["mcp_servers"] = data.get("mcp", {})
            # 收集 opencode.json 中定義的自訂模型
            for prov_cfg in data.get("provider", {}).values():
                for model_key in prov_cfg.get("models", {}):
                    prov_id = list(data.get("provider", {}).keys())[0]
                    meta["available_models"].append(f"{prov_id}/{model_key}")
            # 嘗試從 opencode CLI 取得完整模型清單
            try:
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
                    # 合併去重，CLI 結果為主
                    if cli_models:
                        meta["available_models"] = cli_models
            except Exception:
                pass
        except Exception as e:
            logger.warning("opencode_config_load_error", error=str(e))
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

    return meta


def get_agent_status(provider_name: str, model_override: Optional[str] = None) -> tuple[bool, str, object]:
    """取得 provider 可用狀態"""
    config = AgentProviderConfig.load(
        project_dir=PROJECT_DIR,
        crush_config_path=CRUSH_CONFIG_PATH,
        provider_override=provider_name,
        model_override=model_override,
    )
    provider = create_agent_provider(config)
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


def build_question_context_options() -> tuple[list[str], dict[str, dict]]:
    """建立聊天可選題目上下文"""
    mapping: dict[str, dict] = {}
    options = ["不指定題目"]

    generated = st.session_state.get("generated_questions", [])
    for i, q in enumerate(generated, 1):
        label = f"[最近生成 #{i}] {q.get('question_text', '')[:45]}"
        mapping[label] = q
        options.append(label)

    repo_questions = load_questions()[:30]
    for i, q in enumerate(repo_questions, 1):
        qid = q.get("id", "N/A")[:8]
        label = f"[題庫 {qid}] {q.get('question_text', '')[:45]}"
        mapping[label] = q
        options.append(label)

    return options, mapping


def build_discussion_prompt(user_prompt: str, selected_question: dict | None) -> str:
    """將題目上下文包進聊天 prompt"""
    if not selected_question:
        return user_prompt

    context = {
        "question_text": selected_question.get("question_text"),
        "options": selected_question.get("options"),
        "correct_answer": selected_question.get("correct_answer"),
        "explanation": selected_question.get("explanation"),
        "source": selected_question.get("source"),
    }

    return (
        "你正在和使用者討論以下考題，請以這題為主要上下文回答。\n"
        f"題目上下文(JSON): {json.dumps(context, ensure_ascii=False)}\n\n"
        f"使用者問題: {user_prompt}"
    )


def extract_questions_from_response(text: str) -> list[dict]:
    """
    從 AI 混合文字輸出中提取所有 JSON 題目物件。

    AI 回應通常包含敘述文字 + JSON code blocks，需要找出所有
    包含 question_text & options 的 JSON 物件。
    """
    questions: list[dict] = []
    seen_texts: set[str] = set()  # 去重

    # 策略 1：提取 ```json ... ``` 或 ``` ... ``` code blocks
    code_blocks = re.findall(r"```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL)

    # 策略 2：找獨立的 JSON 物件（以 { 開頭且包含 question_text）
    # 使用平衡括號匹配
    brace_objects: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            start = i
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : j + 1]
                        if "question_text" in candidate and "options" in candidate:
                            brace_objects.append(candidate)
                        i = j + 1
                        break
            else:
                i += 1
        else:
            i += 1

    # 合併兩種策略的結果
    for raw_json in code_blocks + brace_objects:
        try:
            obj = json.loads(raw_json)
        except json.JSONDecodeError:
            # 嘗試修復常見問題（trailing comma）
            cleaned = re.sub(r",\s*}", "}", raw_json)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                obj = json.loads(cleaned)
            except json.JSONDecodeError:
                continue

        if not isinstance(obj, dict):
            continue
        if not obj.get("question_text") or not obj.get("options"):
            continue

        # 去重（同一題可能在 code block 和 brace 都被找到）
        fingerprint = obj["question_text"][:80]
        if fingerprint in seen_texts:
            continue
        seen_texts.add(fingerprint)

        questions.append(normalize_ai_question(obj))

    return questions


def normalize_ai_question(raw: dict) -> dict:
    """
    將 AI 輸出的 JSON 格式正規化為我們的 Question schema。

    AI 可能輸出：
      source_doc, source_chapter, stem_source, ...
    我們需要：
      source: { document, chapter, stem_source: {...}, ... }
    """
    q: dict = {
        "id": raw.get("id", str(uuid.uuid4())),
        "question_text": raw.get("question_text", ""),
        "options": raw.get("options", []),
        "correct_answer": raw.get("correct_answer", ""),
        "explanation": raw.get("explanation", ""),
        "difficulty": raw.get("difficulty", "medium"),
        "topics": raw.get("topics", []),
    }

    # 清理選項（移除 "A. " 前綴，因為 UI 會自動加）
    cleaned_options = []
    for opt in q["options"]:
        cleaned = re.sub(r"^[A-Da-d][.、:：]\s*", "", str(opt))
        cleaned_options.append(cleaned)
    q["options"] = cleaned_options

    # 組裝 source
    source: dict = {}
    if raw.get("source_doc"):
        source["document"] = raw["source_doc"]
    elif raw.get("source") and isinstance(raw["source"], dict):
        source = raw["source"]
    if raw.get("source_chapter"):
        source["chapter"] = raw["source_chapter"]
    if raw.get("stem_source") and isinstance(raw["stem_source"], dict):
        source["stem_source"] = raw["stem_source"]
    if raw.get("answer_source") and isinstance(raw["answer_source"], dict):
        source["answer_source"] = raw["answer_source"]
    if raw.get("explanation_sources") and isinstance(raw["explanation_sources"], list):
        source["explanation_sources"] = raw["explanation_sources"]

    if source:
        q["source"] = source

    for key in ("preview_only", "formal_save_ready", "generation_mode", "evidence_pack"):
        if key in raw:
            q[key] = raw[key]

    return q


def parse_mcp_result(text: str) -> Optional[dict]:
    """
    從 Crush 輸出中解析 MCP 工具調用結果
    """
    # 尋找 JSON 格式的結果
    patterns = [
        r'\{[^{}]*"question_id"\s*:\s*"[^"]+?"[^{}]*\}',
        r'\{[^{}]*"success"\s*:\s*true[^{}]*\}',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        for match in matches:
            try:
                result = json.loads(match)
                if result.get("question_id"):
                    return result
            except json.JSONDecodeError:
                continue

    # 尋找題目 ID 格式
    id_match = re.search(r'題目\s*ID[：:]\s*[`"]?([a-f0-9-]{36})[`"]?', text)
    if id_match:
        return {"question_id": id_match.group(1), "success": True}

    return None


def parse_question_from_output(text: str) -> Optional[dict]:
    """從 AI 輸出中解析題目內容"""
    question = {}

    # 解析題目文字
    q_patterns = [
        r"\*\*題目[：:]\*\*\s*(.+?)(?=\*\*選項|\*\*Options|[A-D][.、]|$)",
        r"題目[：:]\s*(.+?)(?=選項|[A-D][.、]|$)",
    ]

    for pattern in q_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            question["question_text"] = match.group(1).strip()
            break

    # 解析選項
    options = []
    opt_pattern = r"([A-D])[.、:：]\s*(.+?)(?=[A-D][.、:：]|\*\*答案|\*\*正確|答案[：:]|$)"
    for match in re.finditer(opt_pattern, text, re.DOTALL):
        opt_text = match.group(2).strip()
        if opt_text and len(opt_text) > 1:
            options.append(opt_text)
    if options:
        question["options"] = options

    # 解析答案
    ans_patterns = [
        r"\*\*(?:答案|正確答案)[：:]\*\*\s*([A-D])",
        r"(?:答案|正確答案)[：:]\s*([A-D])",
    ]

    for pattern in ans_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            question["correct_answer"] = match.group(1).upper()
            break

    # 解析難度
    diff_match = re.search(r"難度[：:]\s*(easy|medium|hard|簡單|中等|困難)", text, re.IGNORECASE)
    if diff_match:
        diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
        question["difficulty"] = diff_map.get(diff_match.group(1), diff_match.group(1).lower())

    # 解析詳解
    exp_patterns = [
        r"\*\*(?:解析|詳解)[：:]\*\*\s*(.+?)(?=\*\*|題目 ID|$)",
        r"(?:解析|詳解)[：:]\s*(.+?)(?=題目|$)",
    ]

    for pattern in exp_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            question["explanation"] = match.group(1).strip()
            break

    if question.get("question_text") and question.get("options"):
        return question

    return None


def stream_agent_generate(
    prompt: str,
    provider,
    output_placeholder,
    questions_container,
    progress_placeholder,
) -> tuple[str, list[dict]]:
    """
    真正的流式生成 - 不使用 st.spinner，持續更新 UI

    Returns:
        (full_output, saved_questions)
    """
    logger.info("generation_start", provider=getattr(provider, "name", "unknown"), prompt_len=len(prompt))
    t0 = time.monotonic()

    full_response = ""
    current_question_buffer = ""
    saved_questions = []
    last_update_time = time.time()

    try:
        for line in provider.stream(prompt):
            if not line:
                continue

            full_response += line
            current_question_buffer += line

            # 每 100ms 更新一次 UI，避免過於頻繁
            current_time = time.time()
            if current_time - last_update_time > 0.1:
                # 更新 AI 輸出顯示
                display_text = full_response[-3000:] if len(full_response) > 3000 else full_response
                output_placeholder.markdown(f"```\n{display_text}\n```")

                # 更新進度
                progress_placeholder.markdown(f"⏳ 已接收 {len(full_response)} 字元，已儲存 {len(saved_questions)} 題")

                last_update_time = current_time

            # 檢查是否有新題目被儲存
            mcp_result = parse_mcp_result(current_question_buffer)
            if mcp_result and mcp_result.get("question_id"):
                qid = mcp_result.get("question_id")
                logger.info("mcp_result_detected", question_id=qid)

                # 解析題目內容
                parsed_q = parse_question_from_output(current_question_buffer)
                if parsed_q:
                    parsed_q["id"] = qid
                    saved_questions.append(parsed_q)

                    logger.info(
                        "question_saved",
                        index=len(saved_questions),
                        question_id=qid,
                        question_text=parsed_q.get("question_text", "")[:80],
                    )

                    # 即時顯示題目卡片
                    with questions_container:
                        render_question_card_inline(parsed_q, len(saved_questions))

                # 重置緩衝區
                current_question_buffer = ""

        # 最終更新
        output_placeholder.markdown(f"```\n{full_response[-3000:]}\n```")

    except Exception as e:
        logger.exception("generation_error", error=str(e))
        output_placeholder.error(f"生成錯誤: {e}")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "generation_done",
        duration_ms=elapsed_ms,
        total_questions=len(saved_questions),
        total_chars=len(full_response),
    )

    return full_response, saved_questions


def stream_agent_response(prompt: str, provider):
    """聊天用流式回應"""
    for chunk in provider.stream(prompt):
        yield chunk


def run_agent_sync(prompt: str, provider) -> str:
    """聊天用同步回應"""
    return provider.run(prompt)


def render_source_info(source: dict | None, expanded: bool = False):
    """渲染來源資訊（可展開式）"""
    if not source:
        return

    # 檢查是否有任何來源資訊
    has_info = source.get("document") or source.get("stem_source") or source.get("page")
    if not has_info:
        return

    with st.expander("📚 來源資訊", expanded=expanded):
        # 基本資訊
        doc = source.get("document", "未知文件")
        st.markdown(f"**📖 教材:** {doc}")

        if source.get("chapter"):
            chapter_str = str(source.get("chapter") or "")
            if source.get("section"):
                chapter_str += f" - {source.get('section')}"
            st.markdown(f"**📑 章節:** {chapter_str}")

        # 精確來源（新格式）
        if source.get("stem_source"):
            st.markdown("---")
            _render_source_location("📍 題幹來源", source["stem_source"])

        if source.get("answer_source"):
            _render_source_location("📍 答案依據", source["answer_source"])

        if source.get("explanation_sources"):
            for i, src in enumerate(source["explanation_sources"]):
                _render_source_location(f"📍 詳解來源 {i + 1}", src)

        # 向後相容（舊格式）
        elif source.get("page") and not source.get("stem_source"):
            st.markdown("---")
            page_info = f"**P.{source['page']}**"
            if source.get("lines"):
                page_info += f", 第 {source['lines']} 行"
            st.markdown(page_info)

            if source.get("original_text"):
                text = source["original_text"]
                if len(text) > 200:
                    text = text[:200] + "..."
                st.markdown(f"> _{text}_")

        # 驗證狀態
        if source.get("is_verified"):
            st.success("✅ 來源已驗證")


def _render_source_location(label: str, loc: dict):
    """渲染單一來源位置"""
    if not loc:
        return

    page = loc.get("page", 0)
    line_start = loc.get("line_start", 0)
    line_end = loc.get("line_end", 0)
    original_text = loc.get("original_text", "")

    # 位置資訊
    loc_str = f"**{label}:** P.{page}"
    if line_start and line_end:
        loc_str += f", 第 {line_start}-{line_end} 行"
    st.markdown(loc_str)

    # 原文引用
    if original_text:
        text = original_text
        if len(text) > 200:
            text = text[:200] + "..."
        st.markdown(f"> _{text}_")


def render_question_card_inline(question: dict, index: int):
    """在容器內渲染題目卡片（用於流式生成時）"""
    st.markdown("---")
    st.markdown(f"### ✅ 第 {index} 題 (已儲存)")
    st.markdown(f"**{question.get('question_text', '')}**")

    options = question.get("options", [])
    for j, opt in enumerate(options):
        prefix = chr(65 + j)
        if prefix == question.get("correct_answer"):
            st.markdown(f"✅ **{prefix}. {opt}**")
        else:
            st.markdown(f"　{prefix}. {opt}")

    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"📝 答案: {question.get('correct_answer', 'N/A')}")
    with col2:
        diff = question.get("difficulty", "medium")
        diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff, "⚪")
        st.caption(f"{diff_emoji} 難度: {diff}")

    if question.get("explanation"):
        with st.expander("📖 查看詳解"):
            st.write(question.get("explanation"))

    # 顯示來源資訊
    source = question.get("source")
    if source:
        render_source_info(source)

    st.caption(f"🆔 {question.get('id', 'N/A')}")


def render_question_review_form(questions: list[dict]) -> None:
    """
    渲染題目審閱/編輯表單。

    顯示從 AI 回應中提取的題目，讓使用者可以：
    1. 預覽完整題目卡片
    2. 編輯題目文字、選項、答案、難度
    3. 查看來源資訊
    4. 先送進草稿箱，再批次整理或正式入庫
    """
    from src.application.services.question_draft_service import get_question_draft_service
    from src.application.services.question_similarity_service import get_question_similarity_service
    from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

    if not questions:
        return

    st.markdown(f"### 📝 AI 生成結果：共 {len(questions)} 題")
    st.caption("建議先送進草稿箱，再用批次編修整理後正式入庫；若確認品質足夠，也可直接正式入庫。")

    preview_only_count = sum(1 for question in questions if question.get("preview_only"))
    formal_ready_count = sum(1 for question in questions if question_formal_save_ready(question))
    blocked_formal_count = len(questions) - formal_ready_count

    if preview_only_count:
        st.warning(
            f"本批有 {preview_only_count} 題屬於 preview-only 草稿，只能送進草稿箱，不能直接正式入庫。"
        )
    elif blocked_formal_count:
        st.warning(
            f"本批有 {blocked_formal_count} 題尚未通過 formal-save gate。請先補足 evidence pack 或改送草稿箱。"
        )
    elif formal_ready_count:
        st.success("本批題目都已具備 formal-save evidence pack，可直接正式入庫。")

    similarity_service = get_question_similarity_service()
    similarity_corpus = similarity_service.build_corpus()
    similar_warning_count = sum(
        1
        for question in questions
        if similarity_service.find_similar(
            question.get("question_text", ""),
            corpus=similarity_corpus,
            threshold=0.78,
        )
    )
    if similar_warning_count:
        st.warning(f"本批候選題中有 {similar_warning_count} 題偵測到相似題，建議先送進草稿箱比對後再正式入庫。")

    # 草稿箱 / 正式入庫 / 清除
    col_draft_all, col_save_all, col_clear = st.columns([1, 1, 1])
    with col_draft_all:
        if st.button("📥 全部送進草稿箱", width="stretch", type="primary", key="save_all_to_drafts"):
            draft_service = get_question_draft_service()
            saved_count = draft_service.save_review_questions_as_drafts(questions, origin="generated_review")
            if saved_count > 0:
                st.session_state.generated_questions = []
                st.session_state.draft_flash = f"已新增 {saved_count}/{len(questions)} 題到草稿箱。"
                navigate_to("🗃️ 草稿箱")
                st.rerun()
            st.error("❌ 無法送進草稿箱，請檢查題目格式")
    with col_save_all:
        if st.button(
            "✅ 全部正式入庫",
            width="stretch",
            key="save_all_reviewed",
            disabled=formal_ready_count != len(questions),
        ):
            repo = get_question_repository()
            saved_count = 0
            for q in questions:
                try:
                    question_entity = _dict_to_question_entity(q)
                    repo.save(question_entity)
                    saved_count += 1
                except Exception as e:
                    logger.warning("save_question_failed", error=str(e), question_text=q.get("question_text", "")[:50])
            if saved_count > 0:
                st.success(f"✅ 已儲存 {saved_count}/{len(questions)} 題到題庫！")
                logger.info("batch_save_completed", saved=saved_count, total=len(questions))
            else:
                st.error("❌ 儲存失敗，請檢查題目格式")
    with col_clear:
        if st.button("🗑️ 清除結果", width="stretch", key="clear_reviewed"):
            st.session_state.generated_questions = []
            st.rerun()

    st.markdown("---")

    # 逐題顯示
    for idx, q in enumerate(questions):
        q_num = idx + 1
        review_key = ensure_review_question_widget_key(q, idx)
        with st.expander(f"第 {q_num} 題：{q.get('question_text', '')[:60]}...", expanded=(idx < 3)):
            evidence_pack = q.get("evidence_pack") or {}
            if q.get("preview_only"):
                st.info("preview-only：這題是從教材 section/chapter/full text 產生的草稿，不可直接正式入庫。")
            elif question_formal_save_ready(q):
                st.success("formal-save ready：stem_source、answer_source、explanation_sources 已齊備。")
            else:
                st.warning("尚未達到 formal-save gate。請先補齊 evidence pack 或先送進草稿箱。")

            gate_reasons = evidence_pack.get("gate_reasons") or []
            if gate_reasons:
                st.caption("Gate: " + " | ".join(str(reason) for reason in gate_reasons))

            # ---- 題目文字（可編輯）----
            edited_text = st.text_area(
                "題目",
                value=q.get("question_text", ""),
                height=100,
                key=f"review_q_text_{review_key}",
            )
            q["question_text"] = edited_text

            # ---- 選項（可編輯）----
            options = q.get("options", [])
            for opt_idx in range(4):
                prefix = chr(65 + opt_idx)
                default_val = options[opt_idx] if opt_idx < len(options) else ""
                edited_opt = st.text_input(
                    f"選項 {prefix}",
                    value=default_val,
                    key=f"review_opt_{review_key}_{opt_idx}",
                )
                if opt_idx < len(options):
                    options[opt_idx] = edited_opt
                elif edited_opt:
                    options.append(edited_opt)
            q["options"] = options

            # ---- 答案 + 難度 ----
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                answer_opts = ["A", "B", "C", "D"]
                current_ans = q.get("correct_answer", "A").upper()
                ans_idx = answer_opts.index(current_ans) if current_ans in answer_opts else 0
                q["correct_answer"] = st.selectbox(
                    "正確答案",
                    answer_opts,
                    index=ans_idx,
                    key=f"review_ans_{review_key}",
                )
            with r_col2:
                diff_opts = ["easy", "medium", "hard"]
                diff_labels = ["🟢 簡單", "🟡 中等", "🔴 困難"]
                current_diff = q.get("difficulty", "medium")
                diff_idx = diff_opts.index(current_diff) if current_diff in diff_opts else 1
                selected_diff = st.selectbox(
                    "難度",
                    diff_labels,
                    index=diff_idx,
                    key=f"review_diff_{review_key}",
                )
                q["difficulty"] = diff_opts[diff_labels.index(selected_diff)]

            # ---- 詳解（可編輯）----
            edited_exp = st.text_area(
                "詳解",
                value=q.get("explanation", ""),
                height=80,
                key=f"review_exp_{review_key}",
            )
            q["explanation"] = edited_exp

            # ---- 主題標籤 ----
            topics_str = ", ".join(q.get("topics", []))
            edited_topics = st.text_input(
                "主題標籤（逗號分隔）",
                value=topics_str,
                key=f"review_topics_{review_key}",
            )
            q["topics"] = [t.strip() for t in edited_topics.split(",") if t.strip()]

            # ---- 來源資訊（唯讀顯示）----
            source = q.get("source")
            if source:
                render_source_info(source, expanded=False)

            similar_matches = similarity_service.find_similar(
                q.get("question_text", ""),
                corpus=similarity_corpus,
                threshold=0.78,
            )
            if similar_matches:
                st.warning("偵測到相似題，送進草稿箱或正式入庫前請先比對。")
                match_lines = []
                for match in similar_matches:
                    source_label = "正式題庫" if match["source_type"] == "bank" else "草稿箱"
                    similarity_pct = int(round(match["similarity"] * 100))
                    preview_text = match["question_text"][:72].strip()
                    if len(match["question_text"]) > 72:
                        preview_text += "..."
                    match_lines.append(f"- [{source_label}] {similarity_pct}% 相似: {preview_text}")
                st.markdown("\n".join(match_lines))

            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button("📥 送進草稿箱", key=f"save_single_draft_{review_key}", width="stretch"):
                    try:
                        draft_service = get_question_draft_service()
                        saved_count = draft_service.save_review_questions_as_drafts([q], origin="review_single")
                        if saved_count:
                            st.success("✅ 已送進草稿箱")
                    except Exception as e:
                        st.error(f"❌ 送進草稿箱失敗: {e}")
            with action_col2:
                if st.button(
                    "💾 正式入庫",
                    key=f"save_single_{review_key}",
                    width="stretch",
                    disabled=not question_formal_save_ready(q),
                ):
                    try:
                        repo = get_question_repository()
                        question_entity = _dict_to_question_entity(q)
                        qid = repo.save(question_entity)
                        st.success(f"✅ 已儲存！ID: {qid[:8]}...")
                        logger.info("single_question_saved", question_id=qid)
                    except Exception as e:
                        st.error(f"❌ 儲存失敗: {e}")


def _dict_to_question_entity(q: dict):
    """將審閱表單的 dict 轉為 Question entity"""
    from src.domain.entities.question import (
        Difficulty,
        Question,
        QuestionType,
        Source,
        SourceLocation,
    )

    source = None
    src_data = q.get("source")
    if src_data and isinstance(src_data, dict):
        stem_loc = None
        if src_data.get("stem_source"):
            sl = src_data["stem_source"]
            stem_loc = SourceLocation(
                page=sl.get("page", 0),
                line_start=sl.get("line_start", 0),
                line_end=sl.get("line_end", 0),
                bbox=tuple(sl["bbox"]) if sl.get("bbox") else None,
                original_text=sl.get("original_text", ""),
            )
        answer_loc = None
        if src_data.get("answer_source"):
            al = src_data["answer_source"]
            answer_loc = SourceLocation(
                page=al.get("page", 0),
                line_start=al.get("line_start", 0),
                line_end=al.get("line_end", 0),
                bbox=tuple(al["bbox"]) if al.get("bbox") else None,
                original_text=al.get("original_text", ""),
            )
        explanation_locs = []
        for explanation_source in src_data.get("explanation_sources", []) or []:
            explanation_locs.append(
                SourceLocation(
                    page=explanation_source.get("page", 0),
                    line_start=explanation_source.get("line_start", 0),
                    line_end=explanation_source.get("line_end", 0),
                    bbox=tuple(explanation_source["bbox"]) if explanation_source.get("bbox") else None,
                    original_text=explanation_source.get("original_text", ""),
                )
            )
        source = Source(
            document=src_data.get("document", ""),
            chapter=src_data.get("chapter"),
            section=src_data.get("section"),
            stem_source=stem_loc,
            answer_source=answer_loc,
            explanation_sources=explanation_locs,
        )

    return Question(
        id=q.get("id", str(uuid.uuid4())),
        question_text=q.get("question_text", ""),
        options=q.get("options", []),
        correct_answer=q.get("correct_answer", ""),
        explanation=q.get("explanation", ""),
        source=source,
        question_type=QuestionType.SINGLE_CHOICE,
        difficulty=Difficulty(q.get("difficulty", "medium")),
        topics=q.get("topics", []),
    )


def render_question_card(question: dict, index: int, show_answer: bool = False):
    """渲染題目卡片"""
    with st.container():
        st.markdown(f"### 📝 第 {index} 題")
        st.markdown(question.get("question_text", ""))

        options = question.get("options", [])
        for j, opt in enumerate(options):
            prefix = chr(65 + j)
            if show_answer and prefix == question.get("correct_answer"):
                st.markdown(f"✅ **{prefix}. {opt}**")
            else:
                st.markdown(f"- {prefix}. {opt}")

        if show_answer:
            st.info(f"**答案:** {question.get('correct_answer', 'N/A')}")
            if question.get("explanation"):
                st.caption(f"📖 {question.get('explanation')}")

        # 顯示元資料
        col1, col2 = st.columns(2)
        with col1:
            diff = question.get("difficulty", "medium")
            diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff, "⚪")
            st.caption(f"{diff_emoji} 難度: {diff}")
        with col2:
            topics = question.get("topics", [])
            if topics:
                st.caption(f"🏷️ {', '.join(topics)}")

        # 顯示來源資訊（可展開）
        source = question.get("source")
        if source:
            render_source_info(source)

        st.markdown("---")


def load_past_exam_catalog(limit: int = 20) -> list[dict]:
    """讀取歷屆考卷清單與摘要資訊。"""
    from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository

    repo = get_past_exam_repository()
    return repo.list_exam_catalog(limit=limit)


def load_past_exam_questions(past_exam_id: str) -> list[dict]:
    """讀取單份歷屆考卷的題目明細。"""
    from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository

    repo = get_past_exam_repository()
    questions = repo.list_questions(past_exam_id)
    return [
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
            "source_doc_id": question.source_doc_id,
            "source_page": question.source_page,
            "exam_name": question.exam_name,
            "exam_year": question.exam_year,
        }
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


def load_question_drafts(status: str | None = None, starred_only: bool = False) -> list[dict]:
    """載入題目草稿箱。"""
    from src.application.services.question_draft_service import get_question_draft_service

    return get_question_draft_service().list_drafts(status=status, starred_only=starred_only, limit=300)


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
            st.markdown(f"**答案:** {question.get('correct_answer', 'N/A')}")
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
        review_col1, review_col2 = st.columns(2)
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
                st.rerun()

        source = question.get("source") or {}
        if source:
            render_source_info(source, expanded=False)


def get_questions_stats() -> dict:
    """取得題庫統計。"""
    from src.application.services.question_bank_query_service import get_question_bank_query_service

    return get_question_bank_query_service().get_content_stats()


def load_questions(validated_only: bool = False, exam_track: str | None = None) -> list[dict]:
    """載入一般題庫題目。"""
    from src.application.services.question_bank_query_service import get_question_bank_query_service

    return get_question_bank_query_service().list_questions(
        validated_only=validated_only,
        exam_track=exam_track,
        limit=500,
    )


def load_scope_requests(status: str | None = None) -> list[dict]:
    """載入出題需求 backlog"""
    from src.domain.entities.scope_request import ScopeRequestStatus
    from src.infrastructure.persistence.sqlite_scope_request_repo import get_scope_request_repository

    repo = get_scope_request_repository()
    status_filter = ScopeRequestStatus(status) if status else None
    requests = repo.list_all(status=status_filter, limit=200)
    return [req.to_dict() for req in requests]


def get_heartbeat_summary() -> dict:
    """取得 heartbeat / backlog 摘要"""
    from src.application.services.heartbeat_service import HeartbeatService

    return HeartbeatService().get_status_summary()


# ===== 初始化 session state =====
if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent_provider_name" not in st.session_state:
    st.session_state.agent_provider_name = "opencode"

if "agent_meta" not in st.session_state:
    st.session_state.agent_meta = load_agent_metadata(st.session_state.agent_provider_name)

if "agent_model" not in st.session_state:
    st.session_state.agent_model = st.session_state.agent_meta.get("model") or ""

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
if "page_nav" not in st.session_state:
    st.session_state.page_nav = st.session_state.current_page
sync_query_params_with_page(st.session_state.current_page)
sync_nav_widget_state()

# 生成狀態
if "generated_questions" not in st.session_state:
    st.session_state.generated_questions = []
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False

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
if "chat_question_context" not in st.session_state:
    st.session_state.chat_question_context = "不指定題目"
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


# ===== 側邊欄 (左側導航) =====
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
        provider_name = st.selectbox(
            "🤖 Agent Provider",
            options=["crush", "opencode", "copilot-sdk"],
            index=["crush", "opencode", "copilot-sdk"].index(st.session_state.agent_provider_name),
            help="切換底層 agent provider（UI 只作為包裝層）",
        )

        if provider_name != st.session_state.agent_provider_name:
            st.session_state.agent_provider_name = provider_name
            st.session_state.agent_meta = load_agent_metadata(provider_name)
            st.session_state.agent_model = st.session_state.agent_meta.get("model") or ""
            available, reason, provider = get_agent_status(provider_name, st.session_state.agent_model or None)
            st.session_state.agent_available = available
            st.session_state.agent_status_reason = reason
            st.session_state.agent_provider = provider
            st.rerun()

        if st.session_state.agent_provider_name == "opencode":
            available_models = st.session_state.agent_meta.get("available_models", [])
            if available_models:
                current_model = st.session_state.agent_model or ""
                if current_model and current_model not in available_models:
                    available_models = [current_model] + available_models
                model_index = available_models.index(current_model) if current_model in available_models else 0

                selected_model = st.selectbox(
                    "🧠 模型",
                    options=available_models,
                    index=model_index,
                    help="切換 OpenCode 使用的 LLM 模型",
                )

                if selected_model != st.session_state.agent_model:
                    st.session_state.agent_model = selected_model
                    st.session_state.agent_meta["model"] = selected_model
                    available, reason, provider = get_agent_status(st.session_state.agent_provider_name, selected_model)
                    st.session_state.agent_available = available
                    st.session_state.agent_status_reason = reason
                    st.session_state.agent_provider = provider
                    st.rerun()

        status = "🟢 已連線" if st.session_state.agent_available else "🔴 未連線"
        st.markdown(f"**Agent 狀態:** {status}")
        st.caption(f"Provider: {st.session_state.agent_provider_name}")
        st.caption(f"狀態訊息: {st.session_state.agent_status_reason}")

        if st.session_state.agent_model:
            st.caption(f"模型: {st.session_state.agent_model}")

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


# ===== 主區域：三欄佈局 (操作區 2/3 + 常駐 Chat 1/3) =====
main_col, chat_col = st.columns([2, 1], gap="medium")


# ===== 左欄：操作區內容 =====
with main_col:
    if page == "📝 生成考題":
        # ===== 考題生成頁面 =====
        indexed_docs_snapshot = load_indexed_documents()
        precise_doc_count = sum(1 for doc in indexed_docs_snapshot if doc.get("has_precise_sources"))
        render_page_hero(
            "AI 考題生成",
            "把教材索引、來源追蹤、題目草擬與審閱收進同一個工作台，正式出題與 preview 草稿會在頁面上明確分流。",
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
        strict_source_tracking = False
        preview_only_mode = False
        missing_precise_docs: list[dict] = []

        with config_section:
            with st.container(border=True):
                st.subheader("Step 1. 先索引教材")
                st.caption("先上傳 PDF 並完成 ETL；若要正式來源追蹤，請使用 Marker 模式。")
                st.markdown(
                    '<div class="section-note">正式來源追蹤建議開啟 Marker 模式。它比較慢，但會保留 blocks.json，之後才能做 page / line / bbox 級的題目來源驗證。</div>',
                    unsafe_allow_html=True,
                )

                etl_col1, etl_col2 = st.columns([1.4, 1])
                with etl_col1:
                    uploaded_pdf = st.file_uploader("上傳教材 PDF", type=["pdf"], key="etl_pdf")
                    etl_title = st.text_input("教材標題", placeholder="如：Miller's Anesthesia 9th", key="etl_title")
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
                    if st.session_state.agent_provider_name not in ("crush", "opencode"):
                        st.error("ETL 需要支援 MCP 的 agent（crush 或 opencode）。")
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
                                    st.success("ETL 已觸發，請確認下方結果與已索引教材清單。")
                                    st.code(result_text)
                                except ValueError as e:
                                    st.error(f"ETL 參數錯誤：{e}")
                                except Exception as e:
                                    st.error(f"ETL 失敗：{e}")

            if st.session_state.etl_last_result:
                with st.expander("最近一次 ETL 回傳", expanded=False):
                    st.code(st.session_state.etl_last_result)

            with st.container(border=True):
                st.subheader("Step 2. 設定出題條件")
                st.caption("先定義題型與難度，再選教材與章節範圍。")
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

                indexed_docs = load_indexed_documents()
                st.markdown("##### 2-2 選擇教材與章節")

                if indexed_docs:
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
                            help="開啟後，若教材缺少 Marker blocks，就不允許正式生成；關閉後可改為 preview 草稿模式。",
                        )

                        precise_ready_count, _missing_precise_count = render_selected_docs_summary(selected_docs_info)
                        missing_precise_docs = [doc for doc in selected_docs_info if not doc.get("has_precise_sources")]
                        preview_only_mode = bool(missing_precise_docs) and not strict_source_tracking

                        if missing_precise_docs:
                            missing_titles = ", ".join(doc["title"] for doc in missing_precise_docs)
                            if strict_source_tracking:
                                st.error(
                                    f"正式模式無法使用目前教材：{missing_titles}。請先用 Marker 重新 ingest，或切換為 preview 草稿模式。"
                                )
                            else:
                                st.warning(
                                    f"目前為 preview 草稿模式：{missing_titles} 缺少精確來源，系統只會生成可審閱草稿，不應直接視為正式入庫題。"
                                )
                        elif precise_ready_count:
                            st.success("已選教材都具備精確來源能力，可走正式來源追蹤流程。")
                else:
                    st.warning("⚠️ 尚無已索引教材。請上傳 PDF 並執行 ETL 索引。")
                    source_doc = st.text_input(
                        "參考教材（可選，無來源追蹤）",
                        placeholder="如：Miller's Anesthesia 第9版",
                        help="手動輸入的教材名稱無法進行精確來源追蹤，只適合 preview 草稿。",
                    )
                    preview_only_mode = True

                additional_instructions = st.text_area(
                    "額外指示（可選）",
                    placeholder="如：請包含臨床案例分析...",
                    height=100,
                )

                generation_blocked = bool(selected_doc_ids and strict_source_tracking and missing_precise_docs)
                st.markdown("##### Step 3. 確認模式並開始生成")
                if preview_only_mode:
                    st.info("目前是 preview 草稿模式：可先驗證內容方向，但不應視為正式入庫題。")
                elif selected_doc_ids:
                    st.success("目前符合正式來源追蹤條件，可直接開始正式生成。")

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

                    # 構建 prompt
                    diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
                    type_map = {"單選題": "MCQ 選擇題", "多選題": "多選題", "是非題": "是非題"}
                    skill_trigger = type_map.get(question_type, "選擇題")
                    diff_en = diff_map.get(difficulty, "medium")

                    prompt = f"""請生成 {num_questions} 道{skill_trigger}。

## 考題配置
- 題型: {question_type}
- 難度: {difficulty} ({diff_en})
- 題數: {num_questions}
"""
                    if topics:
                        prompt += f"- 知識點範圍: {', '.join(topics)}\n"
                    if source_doc:
                        prompt += f"- 參考教材: {source_doc}\n"
                        if selected_doc_ids:
                            prompt += f"- 文件 ID: {', '.join(selected_doc_ids)}\n"
                    prompt += f"- 生成模式: {'preview 草稿' if preview_only_mode else '正式來源追蹤'}\n"
                    if selected_section_details:
                        sec_names = [s["title"] for s in selected_section_details]
                        prompt += f"- 指定章節: {', '.join(sec_names)}\n"
                    if additional_instructions:
                        prompt += f"- 額外要求: {additional_instructions}\n"
                    if prompt_preset != "無":
                        prompt += f"- preset: {prompt_preset} / {PROMPT_PRESETS[prompt_preset]}\n"
                    if textbook_context_bundle.get("prompt_context"):
                        prompt += (
                            "\n## 教材內容上下文（請直接依據以下 section / chapter / full text 出題）\n"
                            + textbook_context_bundle["prompt_context"]
                            + "\n"
                        )

                    # 根據是否有已索引教材來選擇不同的生成流程
                    if source_doc and selected_doc_ids:
                        doc_probe_steps = ""
                        doc_query_steps = ""
                        for did in selected_doc_ids:
                            doc_probe_steps += (
                                f'search_source_location(doc_id="{did}", query="[其中一個 target concept]")\n'
                            )
                            doc_query_steps += f'search_source_location(doc_id="{did}", query="[概念關鍵字]")\n'

                        # 組合章節聚焦指引
                        section_focus = ""
                        if selected_section_details:
                            sec_list = "\n".join(
                                f"  - {s['title']} (P.{s.get('page', '?')}, doc: {s['doc_id'][:12]})"
                                for s in selected_section_details
                            )
                            section_focus = f"""
### 📑 聚焦章節
用戶指定了以下章節，請**優先**從這些章節中提取知識點出題：
{sec_list}

使用 `get_section_content` 讀取指定章節內容：
```
get_section_content(doc_id="<doc_id>", section_id="<section_id>")
```
可用的 section_id：
{chr(10).join(f"  - {s['id']} ({s['title']})" for s in selected_section_details)}
"""

                        if preview_only_mode:
                            prompt += f"""
## Preview 草稿模式（不得假裝有精確來源）

已選教材目前**沒有完整精確來源能力**，因此這次只能生成可審閱草稿：

1. 先做 readiness probe：
```
{doc_probe_steps}```
2. 如果 `consult_knowledge_graph` 可用，可輔助閱讀；若失敗，改以全文/章節內容理解教材。
3. **不得編造頁碼、行號、bbox、original_text。**
4. **不得呼叫 `exam_save_question` 或 `exam_bulk_save` 正式入庫。**
5. 請直接輸出 JSON 題目物件，方便使用者在 UI 內預覽與人工審閱。

{section_focus}
每題仍需提供完整 explanation，包含：
- 為何正解正確
- 每個錯誤選項為何錯
- 一句臨床/考試重點
"""
                        else:
                            prompt += f"""
## 🚨 正式來源追蹤流程（必須遵守）

已選教材具備精確來源能力，請走正式流程：

1. `exam_get_generation_guide(question_type=\"mcq\")`
2. `exam_get_pipeline_blueprint(pipeline_type=\"exam-generation\")`
3. `exam_start_pipeline_run(...)`
4. `exam_get_topics()` 避免重複
5. 先做 readiness probe：
```
{doc_probe_steps}```
6. 查知識：`consult_knowledge_graph(query="[知識點關鍵字]")`
7. 取精確來源：
```
{doc_query_steps}```
8. 若任何 probe 顯示缺少 Marker blocks，必須停止並記錄 blocked，不能假裝完成。
9. 只有在取得真實來源後，才能產生題目與 explanation。

{section_focus}
正式儲存 payload 必須包含真實來源：
```json
{{
    "question_text": "...",
    "options": [...],
    "correct_answer": "A",
    "explanation": "逐一說明選項對錯",
    "source_doc": "{source_doc}",
    "source_chapter": "[章節]",
    "stem_source": {{
        "page": [MCP返回的頁碼],
        "line_start": [起始行],
        "line_end": [結束行],
        "original_text": "[MCP返回的原文]"
    }},
    "difficulty": "{diff_en}",
    "topics": {json.dumps(topics if topics else ["麻醉學"], ensure_ascii=False)}
}}
```
"""
                    elif source_doc:
                        # 有手動輸入的教材名稱，但未索引（提醒需要先索引）
                        prompt += f"""
## ⚠️ 注意：教材未索引

你指定了參考教材「{source_doc}」，但此教材**尚未索引**，無法使用 RAG 查詢精確來源。

### 兩種處理方式：

**方式 A：先索引教材（推薦）**
請用戶上傳 PDF 檔案，然後使用 `ingest_documents` 工具索引：
```
ingest_documents(
    file_paths=["path/to/pdf"],
    async_mode=false,
    use_marker=true,
    page_ranges=["1-120"],
    marker_max_pages_per_chunk=100,
    extract_figures=false
)
```
索引完成後，重新開始生成流程。

**方式 B：直接生成（無來源追蹤）**
如果用戶確認要繼續，可以直接生成題目，但：
- ⚠️ 來源資訊將不完整
- ⚠️ 無法進行來源驗證

請詢問用戶選擇哪種方式。"""
                    else:
                        prompt += (
                            """
## 重要指示
1. 每生成一題，**立即**使用 `exam_save_question` MCP 工具儲存
2. 儲存後繼續生成下一題
3. 每題必須包含完整資訊

## 每題格式
**題目:** [題目文字]
**選項:**
A. [選項A]
B. [選項B]
C. [選項C]
D. [選項D]
**答案:** [A/B/C/D]
**難度:** [easy/medium/hard]
**解析:** [詳細解說]

## MCP 工具參數
exam_save_question 需要：
- question_text: 題目文字
- options: ["選項A", "選項B", "選項C", "選項D"]
- correct_answer: "A" (或 B/C/D)
- explanation: 詳解
- difficulty: \""""
                            + diff_en
                            + """\"
- topics: """
                            + json.dumps(topics if topics else ["麻醉學"], ensure_ascii=False)
                            + """

請開始生成第 1 題。"""
                        )

                    logger.info("ui_generation_start", num_questions=num_questions)

                    # 建立 UI 元素
                    st.markdown("---")
                    st.subheader("🚀 生成中...")

                    # 進度顯示（在最上方）
                    progress_placeholder = st.empty()
                    progress_placeholder.info("⏳ 正在初始化 AI Agent...")

                    # 建立兩欄：左邊 AI 輸出，右邊題目預覽
                    output_col, preview_col = st.columns([1, 1])

                    with output_col:
                        st.markdown("#### 🤖 AI 輸出")
                        output_placeholder = st.empty()
                        output_placeholder.code("等待 AI 回應...", language="text")

                    with preview_col:
                        st.markdown("#### 📋 已儲存的題目")
                        questions_container = st.container()
                        with questions_container:
                            st.caption("題目將在儲存後顯示於此...")

                    # 執行流式生成（不使用 st.spinner）
                    provider = st.session_state.agent_provider
                    full_response, saved_questions = stream_agent_generate(
                        prompt=prompt,
                        provider=provider,
                        output_placeholder=output_placeholder,
                        questions_container=questions_container,
                        progress_placeholder=progress_placeholder,
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
                    st.session_state.last_generation_response = full_response

                    logger.info(
                        "ui_generation_completed",
                        mcp_saved=len(saved_questions),
                        json_extracted=len(extracted),
                        total=len(all_questions),
                    )

                    # 完成訊息
                    if all_questions:
                        formal_ready_count = sum(1 for question in all_questions if question_formal_save_ready(question))
                        preview_only_count = sum(1 for question in all_questions if question.get("preview_only"))
                        progress_placeholder.success(
                            f"✅ 生成完成！共提取 {len(all_questions)} 題"
                            f"（MCP 即存: {len(saved_questions)}, JSON 提取: {len(extracted)}）"
                        )
                        if preview_only_count:
                            st.info(f"其中 {preview_only_count} 題已標記為 preview-only 草稿。")
                        elif formal_ready_count < len(all_questions):
                            st.warning(
                                f"其中 {len(all_questions) - formal_ready_count} 題尚未通過 formal-save gate，請先補 evidence pack 或改送草稿箱。"
                            )
                    else:
                        progress_placeholder.warning("⚠️ 生成完成，但未偵測到題目。")
                        with st.expander("🔍 除錯資訊"):
                            st.markdown("**可能原因：**")
                            st.markdown("1. AI 沒有以 JSON 格式輸出題目")
                            st.markdown("2. AI 沒有正確呼叫 `exam_save_question` MCP 工具")
                            st.markdown("3. MCP Server 沒有正常啟動")
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
                            st.session_state.generated_questions = build_e2e_textbook_review_questions("preview")
                            st.session_state.last_generation_response = "E2E preview-only textbook review payload"
                            st.rerun()
                    with seed_col2:
                        if st.button("🧪 載入教材 formal-save", width="stretch", key="e2e_textbook_formal"):
                            st.session_state.generated_questions = build_e2e_textbook_review_questions("formal")
                            st.session_state.last_generation_response = "E2E formal-save textbook review payload"
                            st.rerun()
                    with seed_col3:
                        if st.button("🧪 清空教材測試資料", width="stretch", key="e2e_textbook_clear"):
                            st.session_state.generated_questions = []
                            st.session_state.last_generation_response = ""
                            st.rerun()

            if st.session_state.generated_questions:
                render_question_review_form(st.session_state.generated_questions)

                # 顯示操作按鈕
                st.markdown("---")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("🔄 再生成一批", width="stretch"):
                        st.session_state.generated_questions = []
                        st.rerun()
                with col2:
                    if st.button("✍️ 立即練習", width="stretch"):
                        qs = st.session_state.generated_questions
                        start_practice_session(
                            qs.copy(),
                            {
                                "source_type": PRACTICE_SOURCE_GENERATED,
                                "label": "生成結果",
                            },
                        )
                        navigate_to("✍️ 作答練習")
                        st.rerun()
                with col3:
                    if st.button("📚 查看題庫", width="stretch"):
                        navigate_to("📚 題庫管理")
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
                    "先設定教材與生成模式。若你要正式入庫，請確認教材顯示為可精確追來源。",
                )

    elif page == "🗃️ 草稿箱":
        from src.application.services.question_draft_service import get_question_draft_service
        from src.application.services.question_similarity_service import get_question_similarity_service

        draft_service = get_question_draft_service()
        similarity_service = get_question_similarity_service()
        similarity_corpus = similarity_service.build_corpus()
        historical_templates = draft_service.list_historical_templates(limit=12)
        template_map = {template["template_id"]: template for template in historical_templates}
        template_ids = list(template_map.keys())
        DRAFT_STATUS_OPTIONS = ["全部", "draft", "promoted", "archived"]
        DRAFT_STATUS_LABELS = {
            "全部": "全部",
            "draft": "草稿",
            "promoted": "已入庫",
            "archived": "已封存",
        }
        QA_STATUS_LABELS = {
            "pending": "待審",
            "ready": "可入庫",
            "needs_revision": "需修訂",
        }
        QA_CHECK_LABELS = {
            "pending": "待檢",
            "pass": "通過",
            "revise": "需修訂",
        }
        QA_STATUS_OPTIONS = ["pending", "ready", "needs_revision"]
        QA_CHECK_OPTIONS = ["pending", "pass", "revise"]

        render_draft_flash()

        draft_stats = get_draft_stats()
        render_page_hero(
            "題目草稿箱",
            "生成結果先進草稿區，整理好再正式入庫。這裡支援加星、批次編修、批次送入題庫與封存。",
            [
                f"待整理草稿 {draft_stats.get('draft', 0)} 題",
                f"已加星 {draft_stats.get('starred', 0)} 題",
                f"已送入題庫 {draft_stats.get('promoted', 0)} 題",
            ],
        )

        with st.container(border=True):
            st.subheader("歷史題型模板")
            st.caption("模板直接取自已拆解的歷屆題庫，建立新草稿時會一併帶入歷史來源、blueprint 摘要與 QA 初始欄位。")
            if historical_templates:
                selected_template_id = st.selectbox(
                    "選擇歷史模板",
                    template_ids,
                    format_func=lambda template_id: (
                        f"{template_map[template_id]['label']} · {template_map[template_id]['source_exam_year']} 年第 {template_map[template_id]['source_question_number']} 題"
                    )
                    if template_id in template_map
                    else str(template_id),
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
                    st.markdown(
                        f"**主題:** {', '.join(selected_template.get('topics', [])) or '-'}"
                    )
                    st.markdown(f"**Bloom:** {selected_template.get('bloom_level', '-')}")

                template_blueprint = selected_template.get("blueprint", {})
                if template_blueprint.get("recommended_rules"):
                    st.markdown("**Blueprint 指引**")
                    st.markdown(
                        "\n".join(
                            f"- {rule}" for rule in template_blueprint.get("recommended_rules", [])[:3]
                        )
                    )

                if st.button("📐 以歷史模板建立新草稿", width="stretch"):
                    draft_id = draft_service.create_draft_from_template(selected_template_id)
                    if draft_id:
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
                draft_search = st.text_input("搜尋草稿", placeholder="輸入題幹、主題或草稿備註")
            with filter_col2:
                draft_status = st.selectbox(
                    "草稿狀態",
                    DRAFT_STATUS_OPTIONS,
                    format_func=lambda x: DRAFT_STATUS_LABELS.get(x) or str(x),
                    index=0,
                )
            with filter_col3:
                draft_starred_only = st.checkbox("⭐ 只看加星草稿", value=False)

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
            render_empty_state("草稿箱目前沒有符合條件的題目", "先從生成頁把候選題送進草稿箱，或放寬搜尋與篩選條件。")
        else:
            st.dataframe(build_draft_scan_rows(drafts, similarity_map=draft_similarity_map), width="stretch", hide_index=True)

            selection_labels = {
                draft["id"]: f"{'⭐ ' if draft.get('is_starred') else ''}[{DRAFT_STATUS_LABELS.get(draft.get('status', 'draft'), draft.get('status', 'draft'))}] {draft.get('question', {}).get('question_text', '')[:55]}"
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
                selected_draft_ids = list(st.session_state["draft_batch_selection_override"])

            if is_e2e_test_mode():
                if st.button("🧪 E2E 全選目前草稿", width="stretch"):
                    selected_ids = selection_options.copy()
                    st.session_state.draft_batch_selection_override = selected_ids
                    st.rerun()

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
                        qa_label = QA_STATUS_LABELS.get(qa_status, qa_status)
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
                    batch_difficulty = st.selectbox("批次難度", ["不變更", "easy", "medium", "hard"], index=0)
                    batch_validated = st.selectbox(
                        "批次審查狀態",
                        ["不變更", "設為已審查", "設為待審查"],
                        index=0,
                    )
                with edit_col2:
                    batch_exam_track = st.selectbox(
                        "批次考試類型",
                        ["不變更", "ite", "pgy", "clerk", "specialist", "board", "custom"],
                        index=0,
                    )
                    batch_starred = st.selectbox(
                        "批次星號",
                        ["不變更", "加星", "取消加星"],
                        index=0,
                    )
                with edit_col3:
                    batch_topics = st.text_input(
                        "批次主題標籤",
                        placeholder="逗號分隔；留空表示不變更",
                    )
                    batch_notes = st.text_input(
                        "批次草稿備註",
                        placeholder="留空表示不變更",
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
                    )
                with template_apply_col2:
                    batch_replace_content = st.checkbox(
                        "以模板骨架覆蓋題幹/選項",
                        value=False,
                        help="若不勾選，只更新模板引用、blueprint 與建議難度/主題。",
                        disabled=not template_ids,
                    )

                action_col1, action_col2, action_col3 = st.columns(3)
                with action_col1:
                    if st.button("🛠️ 套用批次編修", width="stretch", disabled=not selected_draft_ids):
                        updated = draft_service.bulk_update(
                            draft_ids=selected_draft_ids,
                            difficulty=None if batch_difficulty == "不變更" else batch_difficulty,
                            topics=None if not batch_topics.strip() else [t.strip() for t in batch_topics.split(",") if t.strip()],
                            exam_track=None if batch_exam_track == "不變更" else batch_exam_track,
                            is_validated=None
                            if batch_validated == "不變更"
                            else batch_validated == "設為已審查",
                            is_starred=None
                            if batch_starred == "不變更"
                            else batch_starred == "加星",
                            notes=None if not batch_notes.strip() else batch_notes.strip(),
                        )
                        schedule_draft_batch_selection_reset()
                        set_draft_flash(f"已更新 {updated} 題草稿。")
                        st.rerun()
                with action_col2:
                    if st.button(
                        "📎 套用歷史模板",
                        width="stretch",
                        disabled=not selected_draft_ids or batch_template_id == "不套用",
                    ):
                        updated = draft_service.apply_template_to_drafts(
                            selected_draft_ids,
                            batch_template_id,
                            replace_content=batch_replace_content,
                        )
                        schedule_draft_batch_selection_reset()
                        set_draft_flash(f"已將歷史模板套用到 {updated} 題草稿。")
                        st.rerun()
                with action_col3:
                    if st.button("✅ 送入正式題庫", width="stretch", disabled=not selected_draft_ids):
                        result = draft_service.promote_drafts(selected_draft_ids)
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
                    if st.button("🗂️ 封存選取", width="stretch", disabled=not selected_draft_ids):
                        archived = draft_service.archive_drafts(selected_draft_ids)
                        schedule_draft_batch_selection_reset()
                        set_draft_flash(f"已封存 {archived} 題草稿。")
                        st.rerun()

            for index, draft in enumerate(drafts[:40], start=1):
                question = draft.get("question", {})
                template_data = draft.get("template_data") or {}
                blueprint_data = draft.get("blueprint_data") or {}
                qa_data = draft.get("qa_metadata") or {}
                status_label = DRAFT_STATUS_LABELS.get(draft.get("status", "draft"), draft.get("status", "draft"))
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
                    qa_status_label = QA_STATUS_LABELS.get(qa_status, qa_status)
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
                        st.markdown(f"**答案:** {question.get('correct_answer', '-')}")
                    with detail_col2:
                        st.markdown(f"**難度:** {question.get('difficulty', 'medium')}")
                    with detail_col3:
                        st.markdown(f"**主題:** {', '.join(question.get('topics', [])) or '-'}")

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
                            st.markdown(
                                "\n".join(
                                    f"- {rule}" for rule in blueprint_data.get("recommended_rules", [])[:3]
                                )
                            )

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
                                QA_STATUS_OPTIONS,
                                index=QA_STATUS_OPTIONS.index(qa_data.get("overall_status", "pending"))
                                if qa_data.get("overall_status", "pending") in QA_STATUS_OPTIONS
                                else 0,
                                format_func=lambda value: QA_STATUS_LABELS.get(value) or str(value),
                                key=f"draft_qa_overall_{draft['id']}",
                            )
                            qa_stem = st.selectbox(
                                "題幹品質",
                                QA_CHECK_OPTIONS,
                                index=QA_CHECK_OPTIONS.index(qa_data.get("stem_quality", "pending"))
                                if qa_data.get("stem_quality", "pending") in QA_CHECK_OPTIONS
                                else 0,
                                format_func=lambda value: QA_CHECK_LABELS.get(value) or str(value),
                                key=f"draft_qa_stem_{draft['id']}",
                            )
                        with qa_col2:
                            qa_option = st.selectbox(
                                "選項品質",
                                QA_CHECK_OPTIONS,
                                index=QA_CHECK_OPTIONS.index(qa_data.get("option_quality", "pending"))
                                if qa_data.get("option_quality", "pending") in QA_CHECK_OPTIONS
                                else 0,
                                format_func=lambda value: QA_CHECK_LABELS.get(value) or str(value),
                                key=f"draft_qa_option_{draft['id']}",
                            )
                            qa_answer = st.selectbox(
                                "答案對齊",
                                QA_CHECK_OPTIONS,
                                index=QA_CHECK_OPTIONS.index(qa_data.get("answer_alignment", "pending"))
                                if qa_data.get("answer_alignment", "pending") in QA_CHECK_OPTIONS
                                else 0,
                                format_func=lambda value: QA_CHECK_LABELS.get(value) or str(value),
                                key=f"draft_qa_answer_{draft['id']}",
                            )
                        with qa_col3:
                            qa_source = st.selectbox(
                                "來源對齊",
                                QA_CHECK_OPTIONS,
                                index=QA_CHECK_OPTIONS.index(qa_data.get("source_alignment", "pending"))
                                if qa_data.get("source_alignment", "pending") in QA_CHECK_OPTIONS
                                else 0,
                                format_func=lambda value: QA_CHECK_LABELS.get(value) or str(value),
                                key=f"draft_qa_source_{draft['id']}",
                            )
                            qa_explanation = st.selectbox(
                                "解析品質",
                                QA_CHECK_OPTIONS,
                                index=QA_CHECK_OPTIONS.index(qa_data.get("explanation_quality", "pending"))
                                if qa_data.get("explanation_quality", "pending") in QA_CHECK_OPTIONS
                                else 0,
                                format_func=lambda value: QA_CHECK_LABELS.get(value) or str(value),
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
                                qa_summary = QA_STATUS_LABELS.get(
                                    snapshot_qa.get("overall_status", "pending"),
                                    snapshot_qa.get("overall_status", "pending"),
                                )
                                template_summary = snapshot_template.get("label", "-")
                                reason_text = entry.get("reason") or "-"
                                st.caption(
                                    f"v{entry.get('version_number', '-')} · {entry.get('action', '-')} · {entry.get('created_at', '-') } · {entry.get('actor_name', '-') }"
                                )
                                st.markdown(
                                    f"- 題目：{snapshot_question.get('question_text', '')[:72] or '-'}"
                                )
                                st.markdown(
                                    f"- 模板：{template_summary}｜QA：{qa_summary}｜原因：{reason_text}"
                                )

                    quick_col1, quick_col2 = st.columns(2)
                    with quick_col1:
                        if st.button(
                            "⭐ 取消加星" if draft.get("is_starred") else "⭐ 加星",
                            key=f"draft_star_{draft['id']}",
                            width="stretch",
                        ):
                            draft_service.bulk_update(
                                [draft["id"]],
                                is_starred=not draft.get("is_starred", False),
                            )
                            st.rerun()
                    with quick_col2:
                        if draft.get("status") == "draft" and st.button(
                            "✅ 立即入庫",
                            key=f"draft_promote_{draft['id']}",
                            width="stretch",
                        ):
                            draft_service.promote_drafts([draft["id"]])
                            st.rerun()

                    source = question.get("source") or {}
                    if source:
                        render_source_info(source, expanded=False)

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
                        {int(entry["exam_year"]) for entry in past_exam_catalog if entry.get("exam_year") is not None}
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

                    # 選項
                    options = q.get("options", [])
                    option_labels = [
                        f"{chr(65 + j)}. {opt}" if not opt.startswith(chr(65 + j)) else opt
                        for j, opt in enumerate(options)
                    ]

                    # 作答
                    current_answer = st.session_state.practice_answers.get(q_id, "")
                    try:
                        current_index = option_labels.index(current_answer) if current_answer in option_labels else None
                    except ValueError:
                        current_index = None

                    selected = st.radio(
                        f"選擇答案 (題目 {i + 1})",
                        options=option_labels,
                        index=current_index,
                        key=f"q_{q_id}",
                        label_visibility="collapsed",
                        disabled=st.session_state.practice_submitted,
                    )

                    if selected:
                        st.session_state.practice_answers[q_id] = selected

                    # 已提交時顯示結果
                    if st.session_state.practice_submitted:
                        correct = q.get("correct_answer", "")
                        user_answer = st.session_state.practice_answers.get(q_id, "")
                        user_letter = user_answer[0] if user_answer else ""

                        if user_letter == correct:
                            st.success(f"✅ 正確！答案：{correct}")
                        else:
                            st.error(f"❌ 錯誤！您的答案：{user_letter}，正確答案：{correct}")

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
                col1, col2, col3 = st.columns([1, 1, 1])
                with col2:
                    if st.button("📤 提交答案", width="stretch", type="primary"):
                        st.session_state.practice_submitted = True
                        st.rerun()
            else:
                practice_context = st.session_state.get("practice_context", {})
                practice_result = summarize_practice_results(questions, st.session_state.practice_answers)
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

                    year_tab, exam_tab, pattern_tab, review_tab = st.tabs(
                        [
                            "年度表現",
                            "考卷表現",
                            "題型與主題",
                            f"錯題回顧 ({len(review_rows)})",
                        ]
                    )
                    with year_tab:
                        st.dataframe(year_rows, width="stretch", hide_index=True)
                    with exam_tab:
                        st.dataframe(exam_rows, width="stretch", hide_index=True)
                    with pattern_tab:
                        pattern_col1, pattern_col2 = st.columns(2)
                        with pattern_col1:
                            st.dataframe(pattern_rows, width="stretch", hide_index=True)
                        with pattern_col2:
                            if weak_topic_rows:
                                st.dataframe(weak_topic_rows, width="stretch", hide_index=True)
                            else:
                                st.success("本回合沒有錯題，主題弱點暫時為空。")
                    with review_tab:
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

                                    if row.get("explanation"):
                                        st.info(row["explanation"])

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 重新練習", width="stretch"):
                        start_practice_session(questions, practice_context)
                        st.rerun()
                with col2:
                    if st.button("📝 新的練習", width="stretch"):
                        clear_practice_session()
                        st.rerun()
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
        all_topics = sorted({topic for q in questions for topic in q.get("topics", [])})
        render_page_hero(
            "題庫管理",
            "搜尋、篩選與抽查題庫內容，快速找出要複習、要修正或要拿去練習的題目。",
            [
                f"一般題庫 {len(questions)} 題",
                f"歷屆題庫 {content_stats['past_exam_question_count']} 題",
                f"待審 {content_stats['pending_review_count']} 題",
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
        tab_general, tab_history, tab_review = st.tabs(
            [
                f"一般題庫 ({len(filtered_questions)})",
                f"歷屆題庫 ({content_stats['past_exam_question_count']})",
                f"待審題目 ({len(pending_questions)})",
            ]
        )

        if not questions:
            st.info("📭 題庫空空如也，請先生成考題！")
        else:
            with tab_general:
                summary_col1, summary_col2 = st.columns([1, 1])
                with summary_col1:
                    st.caption(f"顯示 {len(filtered_questions)} / {len(questions)} 題（一般題庫）")
                with summary_col2:
                    if filtered_questions and st.button("✍️ 用目前篩選結果練習", width="stretch"):
                        start_practice_session(
                            filtered_questions[:10],
                            {
                                "source_type": PRACTICE_SOURCE_GENERAL,
                                "label": "題庫篩選結果",
                            },
                        )
                        navigate_to("✍️ 作答練習")
                        st.rerun()

                if not filtered_questions:
                    render_empty_state("沒有符合條件的題目", "試著放寬關鍵字、難度或主題篩選。")
                else:
                    st.dataframe(build_question_scan_rows(filtered_questions), width="stretch", hide_index=True)
                    st.caption("先用表格快速掃描，再展開單題做審查與修正。")
                    for i, question in enumerate(filtered_questions, start=1):
                        render_question_review_expander(question, i, key_prefix="bank_all")

            with tab_history:
                st.caption("歷屆題庫與一般題庫分開存放；這裡列的是已匯入的考古題與考卷。")
                if not past_exam_catalog:
                    render_empty_state("尚未匯入歷屆考卷", "請先執行歷屆考題匯入流程。")
                else:
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
                    past_exam_query = st.text_input(
                        "搜尋歷屆題目",
                        placeholder="輸入關鍵字，例如 malignant hyperthermia",
                        key="past_exam_query",
                    )
                    if past_exam_query:
                        query = past_exam_query.strip().lower()
                        past_exam_questions = [
                            question
                            for question in past_exam_questions
                            if query in question.get("question_text", "").lower()
                        ]

                    st.caption(
                        f"{selected_past_exam['exam_name']}：顯示 {len(past_exam_questions)} / {selected_past_exam['total_questions']} 題"
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
                                "答案": question.get("correct_answer", "") or "-",
                                "頁碼": question.get("source_page") or "-",
                            }
                            for question in past_exam_questions
                        ],
                        width="stretch",
                        hide_index=True,
                    )

            with tab_review:
                st.caption("待審題目 = 一般題庫中尚未標記通過的題目。")
                if not pending_questions:
                    render_empty_state("目前沒有待審題目", "代表目前篩選結果都已審查，或條件過於嚴格。")
                else:
                    st.dataframe(build_question_scan_rows(pending_questions), width="stretch", hide_index=True)
                    for i, question in enumerate(pending_questions, start=1):
                        render_question_review_expander(question, i, key_prefix="bank_pending")

    elif page == "📋 出題需求":
        # ===== 出題需求 / 補題 backlog =====
        from src.application.services.heartbeat_service import HeartbeatService
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
        heartbeat_summary = heartbeat.get_status_summary()
        scope_stats = heartbeat_summary["scope_requests"]

        render_page_hero(
            "出題需求與補題 Backlog",
            "使用者可提交缺題需求，管理者可核准，heartbeat 會把缺口寫成 job 檔案交給外部 agent 補題。",
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

                        action_col1, action_col2 = st.columns(2)
                        with action_col1:
                            if st.button("✅ 核准需求", key=f"scope_approve_{req.get('id')}", width="stretch"):
                                scope_repo.update_status(
                                    req["id"],
                                    ScopeRequestStatus.APPROVED,
                                    admin_notes=admin_note or None,
                                )
                                st.rerun()
                        with action_col2:
                            if st.button("❌ 駁回需求", key=f"scope_reject_{req.get('id')}", width="stretch"):
                                scope_repo.update_status(
                                    req["id"],
                                    ScopeRequestStatus.REJECTED,
                                    admin_notes=admin_note or None,
                                )
                                st.rerun()

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
    with st.container(border=True):
        st.subheader("💬 AI 助手")

        context_options, context_mapping = build_question_context_options()
        if st.session_state.chat_question_context not in context_options:
            st.session_state.chat_question_context = "不指定題目"
        st.session_state.chat_question_context = st.selectbox(
            "討論題目上下文",
            context_options,
            index=context_options.index(st.session_state.chat_question_context),
            help="可先指定一題，再和 AI 討論題目與詳解",
        )

        selected_question = context_mapping.get(st.session_state.chat_question_context)
        if selected_question:
            source_state = "精確來源可用" if question_has_precise_source(selected_question) else "來源待補強"
            st.caption(f"目前上下文：{selected_question.get('question_text', '')[:48]} · {source_state}")

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

        chat_container = st.container(height=520)
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        if not st.session_state.agent_available:
            st.warning("⚠️ Agent 未連線")

        prompt = st.chat_input("輸入問題...", key="chat_input", disabled=not st.session_state.agent_available)
        if quick_prompt:
            prompt = quick_prompt

    if prompt:
        # 添加用戶訊息
        st.session_state.messages.append({"role": "user", "content": prompt, "timestamp": datetime.now().isoformat()})

        # 生成回應
        effective_prompt = build_discussion_prompt(prompt, selected_question)

        if st.session_state.agent_available:
            with st.spinner("思考中..."):
                try:
                    full_response = ""
                    for chunk in stream_agent_response(effective_prompt, st.session_state.agent_provider):
                        full_response += chunk
                    response = full_response if full_response else "無回應"
                except Exception:
                    response = run_agent_sync(effective_prompt, st.session_state.agent_provider)
        else:
            response = "[錯誤] Agent 未連線"

        # 添加助手訊息
        st.session_state.messages.append(
            {"role": "assistant", "content": response, "timestamp": datetime.now().isoformat()}
        )

        st.rerun()

    # 清除對話按鈕
    if st.session_state.messages:
        if st.button("🗑️ 清除對話", width="stretch"):
            st.session_state.messages = []
            st.rerun()


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
