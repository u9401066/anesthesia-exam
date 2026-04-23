"""Application service for generated-question review persistence."""

from __future__ import annotations

import uuid

from src.domain.entities.question import Difficulty, Question, QuestionType, Source, SourceLocation
from src.infrastructure.logging import get_logger
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

logger = get_logger(__name__)


class QuestionReviewService:
    """Coordinate review-stage persistence for generated questions."""

    def __init__(self):
        self.question_repo = get_question_repository()
        logger.debug("question_review_service_initialized")

    def save_review_questions_to_bank(self, questions: list[dict]) -> int:
        """Persist a batch of reviewed questions into the formal bank."""
        saved = 0
        for question in questions:
            try:
                self._ensure_formal_bank_supported(question)
                self.question_repo.save(self._dict_to_question_entity(question))
                saved += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "review_question_batch_save_failed",
                    error=str(exc),
                    question_text=str(question.get("question_text", ""))[:80],
                )

        logger.info("review_question_batch_save_completed", saved=saved, total=len(questions))
        return saved

    def save_review_question_to_bank(self, question: dict) -> str:
        """Persist a single reviewed question into the formal bank."""
        self._ensure_formal_bank_supported(question)
        question_id = self.question_repo.save(self._dict_to_question_entity(question))
        logger.info("review_question_saved", question_id=question_id)
        return question_id

    @staticmethod
    def _ensure_formal_bank_supported(question: dict) -> None:
        if str(question.get("pattern") or "").strip().lower() == "image_based":
            raise ValueError("image_based 題目目前不可正式入庫，因題庫尚未支援持久化圖資。")

    @staticmethod
    def _dict_to_question_entity(question_dict: dict) -> Question:
        """Map a Streamlit review payload into the domain entity used by persistence."""
        source = None
        source_data = question_dict.get("source")
        if source_data and isinstance(source_data, dict):
            source = Source(
                document=source_data.get("document", ""),
                chapter=source_data.get("chapter"),
                section=source_data.get("section"),
                stem_source=QuestionReviewService._source_location_from_dict(source_data.get("stem_source")),
                answer_source=QuestionReviewService._source_location_from_dict(source_data.get("answer_source")),
                explanation_sources=[
                    location
                    for location in (
                        QuestionReviewService._source_location_from_dict(explanation_source)
                        for explanation_source in source_data.get("explanation_sources", []) or []
                    )
                    if location is not None
                ],
            )

        return Question(
            id=question_dict.get("id", str(uuid.uuid4())),
            question_text=question_dict.get("question_text", ""),
            options=question_dict.get("options", []),
            correct_answer=question_dict.get("correct_answer", ""),
            explanation=question_dict.get("explanation", ""),
            source=source,
            question_type=QuestionType.SINGLE_CHOICE,
            difficulty=Difficulty(question_dict.get("difficulty", "medium")),
            topics=question_dict.get("topics", []),
        )

    @staticmethod
    def _source_location_from_dict(raw_location: dict | None) -> SourceLocation | None:
        if not raw_location:
            return None

        return SourceLocation(
            page=raw_location.get("page", 0),
            line_start=raw_location.get("line_start", 0),
            line_end=raw_location.get("line_end", 0),
            bbox=tuple(raw_location["bbox"]) if raw_location.get("bbox") else None,
            original_text=raw_location.get("original_text", ""),
        )


_review_service: QuestionReviewService | None = None


def get_question_review_service() -> QuestionReviewService:
    """Return the singleton review service used by presentation controllers."""
    global _review_service
    if _review_service is None:
        _review_service = QuestionReviewService()
    return _review_service