"""Render fragments for the Streamlit generation preview and handoff flow."""

from __future__ import annotations

import hashlib
import json
from typing import Callable

import streamlit as st

from src.application.services.question_similarity_service import get_question_similarity_service
from src.application.services.textbook_generation_service import get_textbook_generation_service
from src.infrastructure.logging import get_logger
from src.presentation.streamlit.generation.controller import clear_generated_questions

logger = get_logger(__name__)


def question_formal_save_ready(question: dict) -> bool:
    """Use the singleton service directly to avoid brittle symbol-level imports."""
    return get_textbook_generation_service().question_formal_save_ready(question)


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

    options = question.get("options", [])
    for option_index, option in enumerate(options):
        prefix = chr(65 + option_index)
        if prefix == question.get("correct_answer"):
            st.markdown(f"✅ **{prefix}. {option}**")
        else:
            st.markdown(f"　{prefix}. {option}")

    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"📝 答案: {question.get('correct_answer', 'N/A')}")
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

            gate_reasons = evidence_pack.get("gate_reasons") or []
            if gate_reasons:
                st.caption("Gate: " + " | ".join(str(reason) for reason in gate_reasons))

            question["question_text"] = st.text_area(
                "題目",
                value=question.get("question_text", ""),
                height=100,
                key=f"review_q_text_{review_key}",
            )

            options = question.get("options", [])
            for option_index in range(4):
                prefix = chr(65 + option_index)
                default_value = options[option_index] if option_index < len(options) else ""
                edited_option = st.text_input(
                    f"選項 {prefix}",
                    value=default_value,
                    key=f"review_opt_{review_key}_{option_index}",
                )
                if option_index < len(options):
                    options[option_index] = edited_option
                elif edited_option:
                    options.append(edited_option)
            question["options"] = options

            answer_col, difficulty_col = st.columns(2)
            with answer_col:
                answer_options = ["A", "B", "C", "D"]
                current_answer = question.get("correct_answer", "A").upper()
                answer_index = answer_options.index(current_answer) if current_answer in answer_options else 0
                question["correct_answer"] = st.selectbox(
                    "正確答案",
                    answer_options,
                    index=answer_index,
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
