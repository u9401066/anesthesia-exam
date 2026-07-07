"""Application service for generated-question review persistence."""

from __future__ import annotations

import uuid

from src.domain.entities.question import Difficulty, Question, QuestionType, Source, SourceLocation
from src.domain.value_objects.answer import coerce_question_type
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
        question_type = coerce_question_type(
            question.get("question_type"),
            fallback_pattern=question.get("pattern"),
        )
        if question_type == "image_based":
            raise ValueError("image_based 題目目前不可正式入庫，因題庫尚未支援持久化圖資。")

    @staticmethod
    def _dict_to_question_entity(question_dict: dict) -> Question:
        """Map a Streamlit review payload into the domain entity used by persistence."""
        question_type = coerce_question_type(
            question_dict.get("question_type"),
            fallback_pattern=question_dict.get("pattern"),
        )
        difficulty = str(question_dict.get("difficulty") or "medium").strip().lower()
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"
        normalized_topics = QuestionReviewService._coerce_str_list(question_dict.get("topics"))
        normalized_options = QuestionReviewService._coerce_str_list(question_dict.get("options"))

        source = None
        source_data = question_dict.get("source")
        if source_data and isinstance(source_data, dict):
            source = Source(
                document=QuestionReviewService._coerce_str(source_data.get("document"), default=""),
                chapter=QuestionReviewService._coerce_str(source_data.get("chapter"), default=None),
                section=QuestionReviewService._coerce_str(source_data.get("section"), default=None),
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
                page=QuestionReviewService._coerce_int(
                    source_data.get("page"),
                    default=0,
                )
                or None,
                lines=QuestionReviewService._coerce_str(source_data.get("lines"), default=None),
                original_text=QuestionReviewService._coerce_str(source_data.get("original_text"), default=None),
            )

        return Question(
            id=question_dict.get("id", str(uuid.uuid4())),
            question_text=QuestionReviewService._coerce_str(question_dict.get("question_text"), default=""),
            options=normalized_options,
            correct_answer=QuestionReviewService._coerce_str(question_dict.get("correct_answer"), default=""),
            explanation=QuestionReviewService._coerce_str(question_dict.get("explanation"), default=""),
            source=source,
            question_type={
                "single_choice": QuestionType.SINGLE_CHOICE,
                "multiple_choice": QuestionType.MULTIPLE_CHOICE,
                "true_false": QuestionType.TRUE_FALSE,
                "fill_in_blank": QuestionType.FILL_IN_BLANK,
                "short_answer": QuestionType.SHORT_ANSWER,
                "essay": QuestionType.ESSAY,
                "image_based": QuestionType.IMAGE_BASED,
            }.get(question_type, QuestionType.SINGLE_CHOICE),
            difficulty=Difficulty(difficulty),
            topics=normalized_topics,
        )

    @staticmethod
    def _coerce_int(value, *, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
                try:
                    return int(text)
                except ValueError:
                    return default
        return default

    @staticmethod
    def _coerce_str(value, default: str = "") -> str | None:
        if value is None:
            return default
        value = str(value).strip()
        return value or default

    @staticmethod
    def _coerce_str_list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _source_location_from_dict(raw_location: dict | None) -> SourceLocation | None:
        if not isinstance(raw_location, dict):
            return None
        bbox = raw_location.get("bbox")
        parsed_bbox = None
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                parsed_bbox = (
                    float(bbox[0]),
                    float(bbox[1]),
                    float(bbox[2]),
                    float(bbox[3]),
                )
            except (TypeError, ValueError):
                parsed_bbox = None

        return SourceLocation(
            page=QuestionReviewService._coerce_int(raw_location.get("page"), default=0),
            line_start=QuestionReviewService._coerce_int(raw_location.get("line_start"), default=0),
            line_end=QuestionReviewService._coerce_int(raw_location.get("line_end"), default=0),
            bbox=parsed_bbox,
            original_text=QuestionReviewService._coerce_str(raw_location.get("original_text"), default="") or "",
        )


_review_service: QuestionReviewService | None = None


def get_question_review_service() -> QuestionReviewService:
    """Return the singleton review service used by presentation controllers."""
    global _review_service
    if _review_service is None:
        _review_service = QuestionReviewService()
    return _review_service
