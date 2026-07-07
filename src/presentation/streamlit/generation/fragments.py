"""Render fragments for the Streamlit generation preview and handoff flow."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Callable

import streamlit as st

from src.domain.value_objects.answer import (
    format_answer_letters as _format_answer_letters,
    coerce_question_type as _coerce_question_type,
    normalize_answer_letters as _normalize_answer_letters,
    question_allows_multiple as _question_allows_multiple,
)
from src.application.services.question_similarity_service import get_question_similarity_service
from src.application.services.textbook_generation_service import get_textbook_generation_service
from src.infrastructure.logging import get_logger
from src.presentation.streamlit.generation.controller import clear_generated_questions

logger = get_logger(__name__)


def _build_option_label(index: int, option: object) -> str:
    prefix = chr(65 + index)
    option_text = str(option or "").strip()
    if not option_text:
        return f"{prefix}. "
    if re.match(rf"^{re.escape(prefix)}[\)\.:：、\s]", option_text):
        return option_text
    return f"{prefix}. {option_text}"


def question_formal_save_ready(question: dict) -> bool:
    """Use the singleton service directly to avoid brittle symbol-level imports."""
    return get_textbook_generation_service().question_formal_save_ready(question)


def _review_question_type(question: dict) -> str:
    return _coerce_question_type(
        question.get("question_type"),
        fallback_pattern=question.get("pattern"),
    )


_QUESTION_TYPE_LABELS = {
    "single_choice": "單選題",
    "multiple_choice": "多選題",
    "true_false": "是非題",
    "fill_in_blank": "填空題",
    "short_answer": "簡答題",
    "essay": "問答題",
    "image_based": "圖片題",
}

_CHOICE_QUESTION_TYPES = {"single_choice", "multiple_choice", "true_false", "image_based"}


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


def render_source_info(source: dict | None, expanded: bool = False) -> None:
    """Render textbook source metadata in an expandable card."""
    if not source:
        return

    has_info = source.get("document") or source.get("stem_source") or source.get("page")
    if not has_info:
        return

    with st.expander("📚 來源資訊", expanded=expanded):
        doc = source.get("document", "未知文件")
        st.markdown(f"**📖 教材:** {doc}")

        if source.get("chapter"):
            chapter_str = str(source.get("chapter") or "")
            if source.get("section"):
                chapter_str += f" - {source.get('section')}"
            st.markdown(f"**📑 章節:** {chapter_str}")

        if source.get("stem_source"):
            st.markdown("---")
            _render_source_location("📍 題幹來源", source["stem_source"])

        if source.get("answer_source"):
            _render_source_location("📍 答案依據", source["answer_source"])

        if source.get("explanation_sources"):
            for index, explanation_source in enumerate(source["explanation_sources"]):
                _render_source_location(f"📍 詳解來源 {index + 1}", explanation_source)
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

        if source.get("is_verified"):
            st.success("✅ 來源已驗證")


def _render_source_location(label: str, location: dict) -> None:
    if not location:
        return

    page = location.get("page", 0)
    line_start = location.get("line_start", 0)
    line_end = location.get("line_end", 0)
    original_text = location.get("original_text", "")

    location_text = f"**{label}:** P.{page}"
    if line_start and line_end:
        location_text += f", 第 {line_start}-{line_end} 行"
    st.markdown(location_text)

    if original_text:
        text = original_text
        if len(text) > 200:
            text = text[:200] + "..."
        st.markdown(f"> _{text}_")


def render_question_card_inline(question: dict, index: int) -> None:
    """Render a generated question card inline during streaming."""
    st.markdown("---")
    st.markdown(f"### ✅ 第 {index} 題 (已儲存)")
    st.markdown(f"**{question.get('question_text', '')}**")

    options = list(question.get("options", []) or [])
    option_count = len(options)
    correct_letters = _normalize_answer_letters(question.get("correct_answer", ""), option_count=option_count)

    for option_index, option in enumerate(options):
        prefix = chr(65 + option_index)
        option_label = _build_option_label(option_index, option)
        if prefix in correct_letters:
            st.markdown(f"✅ **{option_label}**")
        else:
            st.markdown(f"　{option_label}")

    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"📝 答案: {_format_answer_letters(correct_letters) or '-'}")
    with col2:
        difficulty = question.get("difficulty", "medium")
        difficulty_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(difficulty, "⚪")
        st.caption(f"{difficulty_emoji} 難度: {difficulty}")

    if question.get("explanation"):
        with st.expander("📖 查看詳解"):
            st.write(question.get("explanation"))

    semantic_structure = question.get("semantic_structure")
    if semantic_structure:
        with st.expander("🧭 題目骨架"):
            st.json(semantic_structure)

    source = question.get("source")
    if source:
        render_source_info(source)

    st.caption(f"🆔 {question.get('id', 'N/A')}")


def render_question_review_form(
    questions: list[dict],
    navigate_to: Callable[[str], None],
    *,
    auto_saved_to_drafts: bool = False,
    question_context_callback: Callable[[dict, str], None] | None = None,
) -> None:
    """Render the generated-question preview UI and dispatch navigation actions."""
    if not questions:
        return

    st.markdown(f"### 📝 AI 生成結果：共 {len(questions)} 題")
    if auto_saved_to_drafts:
        st.caption("這裡保留生成結果預覽；待審、QA 與正式入庫入口已移到題庫管理。")
    else:
        st.caption("這裡保留生成結果預覽；若要審題、QA 或正式入庫，請前往題庫管理。")

    preview_only_count = sum(1 for question in questions if question.get("preview_only"))
    formal_ready_count = sum(1 for question in questions if question_formal_save_ready(question))
    blocked_formal_count = len(questions) - formal_ready_count

    if preview_only_count:
        st.warning(
            f"本批有 {preview_only_count} 題屬於 preview-only 題目，只供工作台預覽，請到題庫管理進行審閱。"
        )
    elif blocked_formal_count:
        st.warning(
            f"本批有 {blocked_formal_count} 題尚未通過 formal-save gate。請先補足 evidence pack，或到題庫管理整理。"
        )
    elif formal_ready_count:
        st.success("本批題目都已具備 formal-save evidence pack，可在題庫管理進行入庫。")

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
        st.warning(f"本批候選題中有 {similar_warning_count} 題偵測到相似題，建議到題庫管理比對後再入庫。")

    action_col1, action_col2, action_col3 = st.columns([1.25, 1, 1])
    with action_col1:
        st.info("工作台保留生成預覽與內容修整，待審與入庫請到題庫管理。")
    with action_col2:
        if st.button("📚 前往題庫管理", width="stretch", key="review_open_question_bank"):
            navigate_to("📚 題庫管理")
            st.rerun()
    with action_col3:
        if st.button("🗑️ 清除本批預覽" if auto_saved_to_drafts else "🗑️ 清除結果", width="stretch", key="clear_reviewed"):
            clear_generated_questions()
            st.rerun()

    st.markdown("---")

    for index, question in enumerate(questions):
        question_number = index + 1
        review_key = ensure_review_question_widget_key(question, index)
        with st.expander(f"第 {question_number} 題：{question.get('question_text', '')[:60]}...", expanded=(index < 3)):
            evidence_pack = question.get("evidence_pack") or {}
            if question.get("preview_only"):
                st.info("preview-only：這題只供工作台預覽，請到題庫管理進行審閱後再決定是否入庫。")
            elif question_formal_save_ready(question):
                st.success("formal-save ready：stem_source、answer_source、explanation_sources 已齊備，可到題庫管理入庫。")
            else:
                st.warning("尚未達到 formal-save gate。請先補齊 evidence pack，或到題庫管理整理。")

            if question_context_callback and st.button(
                "🦞 問龍蝦這題",
                key=f"review_chat_{review_key}",
                width="stretch",
            ):
                question_context_callback(question, "生成預覽")

            gate_reasons = evidence_pack.get("gate_reasons") or []
            if gate_reasons:
                st.caption("Gate: " + " | ".join(str(reason) for reason in gate_reasons))

            question["question_text"] = st.text_area(
                "題目",
                value=question.get("question_text", ""),
                height=100,
                key=f"review_q_text_{review_key}",
            )

            question_type_options = list(_QUESTION_TYPE_LABELS)
            current_question_type = _review_question_type(question)
            if current_question_type not in question_type_options:
                current_question_type = "single_choice"
            selected_question_type = st.selectbox(
                "題型",
                question_type_options,
                index=question_type_options.index(current_question_type),
                format_func=lambda value: _QUESTION_TYPE_LABELS.get(value, value),
                key=f"review_type_{review_key}",
            )
            question["question_type"] = selected_question_type
            allow_choice_answer = selected_question_type in _CHOICE_QUESTION_TYPES

            if allow_choice_answer:
                options = list(question.get("options", []) or [])
                default_option_count = 2 if selected_question_type == "true_false" else 4
                default_option_count = min(8, max(2, len(options) or default_option_count))
                option_count = st.number_input(
                    "選項數",
                    min_value=2,
                    max_value=8,
                    value=default_option_count,
                    step=1,
                    key=f"review_option_count_{review_key}",
                    disabled=(selected_question_type == "true_false"),
                )
                option_count = int(option_count)
                for option_index in range(option_count):
                    default_value = options[option_index] if option_index < len(options) else ""
                    edited_option = st.text_input(
                        f"選項 {chr(65 + option_index)}",
                        value=default_value,
                        key=f"review_opt_{review_key}_{option_index}",
                    )
                    if option_index < len(options):
                        options[option_index] = edited_option
                    elif edited_option:
                        options.append(edited_option)
                question["options"] = [option for option in options[:option_count] if str(option).strip()]

                answer_options = [chr(65 + answer_index) for answer_index in range(option_count)]
                normalized_correct = _normalize_answer_letters(question.get("correct_answer", ""), option_count=option_count)
                allows_multiple = _question_allows_multiple(question, option_count=option_count)

                answer_col, difficulty_col = st.columns(2)
                with answer_col:
                    if allows_multiple:
                        selected_answers = st.multiselect(
                            "正確答案（可複選）",
                            answer_options,
                            default=[answer for answer in normalized_correct if answer in answer_options],
                            key=f"review_ans_{review_key}",
                        )
                        question["correct_answer"] = _format_answer_letters(selected_answers)
                    else:
                        current_answer = normalized_correct[0] if normalized_correct else "A"
                        if current_answer not in answer_options:
                            current_answer = "A"
                        question["correct_answer"] = st.selectbox(
                            "正確答案",
                            answer_options,
                            index=answer_options.index(current_answer),
                            key=f"review_ans_{review_key}",
                        )
            else:
                answer_col, difficulty_col = st.columns(2)
                with answer_col:
                    question["correct_answer"] = st.text_area(
                        "正確答案",
                        value=question.get("correct_answer", ""),
                        key=f"review_ans_{review_key}",
                    )

            with difficulty_col:
                difficulty_options = ["easy", "medium", "hard"]
                difficulty_labels = ["🟢 簡單", "🟡 中等", "🔴 困難"]
                current_difficulty = question.get("difficulty", "medium")
                difficulty_index = difficulty_options.index(current_difficulty) if current_difficulty in difficulty_options else 1
                selected_difficulty = st.selectbox(
                    "難度",
                    difficulty_labels,
                    index=difficulty_index,
                    key=f"review_diff_{review_key}",
                )
                question["difficulty"] = difficulty_options[difficulty_labels.index(selected_difficulty)]

            question["explanation"] = st.text_area(
                "詳解",
                value=question.get("explanation", ""),
                height=80,
                key=f"review_exp_{review_key}",
            )

            topics_str = ", ".join(question.get("topics", []))
            edited_topics = st.text_input(
                "主題標籤（逗號分隔）",
                value=topics_str,
                key=f"review_topics_{review_key}",
            )
            question["topics"] = [topic.strip() for topic in edited_topics.split(",") if topic.strip()]

            semantic_structure = question.get("semantic_structure")
            if semantic_structure:
                with st.expander("🧭 題目骨架", expanded=False):
                    st.json(semantic_structure)

            source = question.get("source")
            if source:
                render_source_info(source, expanded=False)

            similar_matches = similarity_service.find_similar(
                question.get("question_text", ""),
                corpus=similarity_corpus,
                threshold=0.78,
            )
            if similar_matches:
                st.warning("偵測到相似題，正式入庫前請先在題庫管理比對。")
                match_lines = []
                for match in similar_matches:
                    source_label = "正式題庫" if match["source_type"] == "bank" else "待審項目"
                    similarity_pct = int(round(match["similarity"] * 100))
                    preview_text = match["question_text"][:72].strip()
                    if len(match["question_text"]) > 72:
                        preview_text += "..."
                    match_lines.append(f"- [{source_label}] {similarity_pct}% 相似: {preview_text}")
                st.markdown("\n".join(match_lines))

            if auto_saved_to_drafts:
                st.caption("這題已可在題庫管理進行待審、QA 與正式入庫。")
            else:
                st.caption("這題尚未進入題庫管理流程。")
