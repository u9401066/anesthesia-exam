"""Controller actions for the Streamlit generation review flow."""

from __future__ import annotations

import streamlit as st

from src.application.services.question_draft_service import get_question_draft_service
from src.application.services.question_review_service import get_question_review_service


def clear_generated_questions() -> None:
    """Clear the in-session generated review payload."""
    st.session_state.generated_questions = []
    st.session_state.generated_questions_auto_saved = False


def save_review_questions_to_drafts(questions: list[dict]) -> int:
    """Persist the current review batch into the draft box and update UI flash state."""
    saved_count = get_question_draft_service().save_review_questions_as_drafts(
        questions,
        origin="generated_review",
    )
    if saved_count > 0:
        clear_generated_questions()
        st.session_state.draft_flash = f"已新增 {saved_count}/{len(questions)} 題到草稿箱。"
        st.session_state.draft_flash_level = "success"
    return saved_count


def save_review_question_to_draft(question: dict) -> bool:
    """Persist a single reviewed question into the draft box."""
    saved_count = get_question_draft_service().save_review_questions_as_drafts(
        [question],
        origin="review_single",
    )
    return saved_count > 0


def save_review_questions_to_bank(questions: list[dict]) -> int:
    """Persist the current review batch into the formal question bank."""
    return get_question_review_service().save_review_questions_to_bank(questions)


def save_review_question_to_bank(question: dict) -> str:
    """Persist a single reviewed question into the formal question bank."""
    return get_question_review_service().save_review_question_to_bank(question)


def autosave_generated_questions_to_drafts(questions: list[dict]) -> int:
    """Persist a generated batch into the pending-draft queue without clearing the preview."""
    saved_count = get_question_draft_service().save_review_questions_as_drafts(
        questions,
        origin="generated_autosave",
    )
    if saved_count > 0:
        st.session_state.draft_flash = f"本批生成結果已自動送入待審草稿 {saved_count}/{len(questions)} 題。"
        st.session_state.draft_flash_level = "success"
    return saved_count
