"""Application service for the draft question workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.application.services.question_template_service import get_question_template_service
from src.domain.entities.question import Difficulty, Question
from src.domain.entities.question_draft import (
    DraftBlueprint,
    DraftChecklistStatus,
    DraftQAMetadata,
    DraftQAStatus,
    QuestionDraft,
    QuestionDraftStatus,
    classify_source_confidence,
)
from src.infrastructure.persistence.database import get_connection
from src.infrastructure.persistence.sqlite_question_draft_repo import get_question_draft_repository
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository


class QuestionDraftService:
    """Coordinate draft persistence, batch editing, and promotion."""

    def __init__(self):
        self.draft_repo = get_question_draft_repository()
        self.question_repo = get_question_repository()
        self.template_service = get_question_template_service()

    def save_review_questions_as_drafts(self, questions: list[dict], origin: str = "generated_review") -> int:
        saved = 0
        for question_dict in questions:
            question = Question.from_dict(question_dict)
            draft = QuestionDraft(
                question=question,
                source_confidence=classify_source_confidence(question),
                origin=origin,
                blueprint_data=self._build_default_blueprint(question),
                qa_metadata=DraftQAMetadata(),
            )
            self.draft_repo.save(
                draft,
                actor_name=origin,
                reason="Saved from generation review",
                action="created",
            )
            saved += 1
        return saved

    def list_drafts(
        self,
        status: Optional[str] = None,
        starred_only: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        status_filter = QuestionDraftStatus(status) if status else None
        drafts = self.draft_repo.list_all(status=status_filter, starred_only=starred_only, limit=limit)
        return [draft.to_dict() for draft in drafts]

    def get_statistics(self) -> dict:
        return self.draft_repo.get_statistics()

    def list_historical_templates(self, limit: int = 8) -> list[dict]:
        return self.template_service.list_templates(limit=limit)

    def create_draft_from_template(self, template_id: str, actor_name: str = "streamlit-admin") -> str | None:
        draft = self.template_service.build_draft_from_template(template_id)
        if draft is None:
            return None
        self.draft_repo.save(
            draft,
            actor_name=actor_name,
            reason=f"Created from historical template {template_id}",
            action="template_created",
        )
        return draft.id

    def apply_template_to_drafts(
        self,
        draft_ids: list[str],
        template_id: str,
        replace_content: bool = False,
        actor_name: str = "streamlit-admin",
    ) -> int:
        if not draft_ids:
            return 0

        template = self.template_service.get_template(template_id)
        if template is None:
            return 0

        template_draft = self.template_service.build_draft_from_template(template_id)
        if template_draft is None or template_draft.template_data is None:
            return 0

        updated = 0
        for draft_id in draft_ids:
            draft = self.draft_repo.get_by_id(draft_id)
            if draft is None:
                continue

            draft.template_data = template_draft.template_data
            draft.blueprint_data = DraftBlueprint.from_dict(template.get("blueprint"))

            template_difficulty = template.get("difficulty", Difficulty.MEDIUM.value)
            draft.question.difficulty = (
                Difficulty(template_difficulty)
                if template_difficulty in {difficulty.value for difficulty in Difficulty}
                else Difficulty.MEDIUM
            )
            draft.question.topics = list(template.get("topics", []))

            if replace_content:
                option_count = max(int(template.get("option_count", 4) or 4), 4)
                draft.question.question_text = template.get("stem_scaffold", draft.question.question_text)
                draft.question.options = [f"選項 {chr(65 + index)}（待編修）" for index in range(option_count)]
                draft.question.correct_answer = ""
                draft.question.explanation = ""
                draft.question.is_validated = False
                draft.question.validation_notes = None

            self.draft_repo.save(
                draft,
                actor_name=actor_name,
                reason=f"Applied historical template {template_id}",
                action="template_applied",
            )
            updated += 1

        return updated

    def bulk_update(
        self,
        draft_ids: list[str],
        difficulty: Optional[str] = None,
        topics: Optional[list[str]] = None,
        exam_track: Optional[str] = None,
        is_validated: Optional[bool] = None,
        is_starred: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> int:
        return self.draft_repo.bulk_update(
            draft_ids=draft_ids,
            difficulty=difficulty,
            topics=topics,
            exam_track=exam_track,
            is_validated=is_validated,
            is_starred=is_starred,
            notes=notes,
            actor_name="streamlit-admin",
            reason="Batch update from draft box",
        )

    def archive_drafts(self, draft_ids: list[str]) -> int:
        return self.draft_repo.archive(
            draft_ids,
            actor_name="streamlit-admin",
            reason="Archived from draft box",
        )

    def get_draft_history(self, draft_id: str, limit: int = 12) -> list[dict]:
        history = self.draft_repo.get_history(draft_id, limit=limit)
        return [entry.to_dict() for entry in history]

    def update_qa_metadata(
        self,
        draft_id: str,
        overall_status: str,
        stem_quality: str,
        option_quality: str,
        answer_alignment: str,
        source_alignment: str,
        explanation_quality: str,
        review_notes: str = "",
        reviewer: str = "streamlit-admin",
        similarity_warning_count: int = 0,
    ) -> bool:
        draft = self.draft_repo.get_by_id(draft_id)
        if draft is None:
            return False

        draft.qa_metadata = DraftQAMetadata(
            overall_status=DraftQAStatus(overall_status),
            stem_quality=DraftChecklistStatus(stem_quality),
            option_quality=DraftChecklistStatus(option_quality),
            answer_alignment=DraftChecklistStatus(answer_alignment),
            source_alignment=DraftChecklistStatus(source_alignment),
            explanation_quality=DraftChecklistStatus(explanation_quality),
            review_notes=review_notes,
            reviewer=reviewer,
            reviewed_at=datetime.now(),
            similarity_warning_count=similarity_warning_count,
        )
        self.draft_repo.save(
            draft,
            actor_name=reviewer,
            reason="QA metadata updated",
            action="qa_updated",
        )
        return True

    def promote_drafts(self, draft_ids: list[str], actor_name: str = "streamlit-admin") -> dict:
        promoted = 0
        failed: list[str] = []

        for draft_id in draft_ids:
            draft = self.draft_repo.get_by_id(draft_id)
            if draft is None:
                failed.append(draft_id)
                continue

            try:
                self._promote_draft_in_single_transaction(draft_id, draft, actor_name)
                promoted += 1
            except Exception:
                failed.append(draft_id)

        return {"promoted": promoted, "failed": failed}

    def _promote_draft_in_single_transaction(self, draft_id: str, draft: QuestionDraft, actor_name: str) -> str:
        question_db_path = getattr(self.question_repo, "db_path", None)
        draft_db_path = getattr(self.draft_repo, "db_path", None)
        if question_db_path != draft_db_path:
            raise RuntimeError("Question and draft repositories must share the same database for atomic promote")

        with get_connection(question_db_path) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                question_id = self.question_repo.save_with_connection(
                    conn,
                    draft.question,
                    actor_name=actor_name,
                    commit=False,
                )
                promoted = self.draft_repo.mark_promoted_with_connection(
                    conn,
                    draft_id,
                    question_id,
                    actor_name=actor_name,
                    reason="Promoted to formal question bank",
                )
                if not promoted:
                    raise RuntimeError(f"Draft {draft_id} could not be marked as promoted")
                conn.commit()
                return question_id
            except Exception:
                conn.rollback()
                raise

    def _build_default_blueprint(self, question: Question) -> DraftBlueprint:
        return DraftBlueprint(
            difficulty=question.difficulty.value,
            target_topics=list(question.topics),
            reference_concepts=list(question.topics),
            recommended_rules=[
                "補上對應的歷史模板或作者 blueprint，再正式入庫。",
                "確認題幹、正解、解析與來源四者一致。",
            ],
        )


_service: QuestionDraftService | None = None


def get_question_draft_service() -> QuestionDraftService:
    """Return singleton draft workflow service."""
    global _service
    if _service is None:
        _service = QuestionDraftService()
    return _service
