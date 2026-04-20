"""Read-oriented query service for question bank UI views."""

from __future__ import annotations

from inspect import signature
from pathlib import Path

from src.domain.entities.question import ExamTrack
from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

PROJECT_DIR = Path(__file__).resolve().parents[3]
EXAMS_DIR = PROJECT_DIR / "data" / "exams"


class QuestionBankQueryService:
    """Aggregate read models needed by the Streamlit question bank UI."""

    def __init__(self, exams_dir: Path | None = None):
        self.question_repo = get_question_repository()
        self.past_exam_repo = get_past_exam_repository()
        self.exams_dir = exams_dir or EXAMS_DIR

    def get_content_stats(self) -> dict:
        """Return combined stats for general bank, past exams, and generated exam files."""
        self.exams_dir.mkdir(parents=True, exist_ok=True)

        question_stats = self.question_repo.get_statistics()
        past_exam_stats = self.past_exam_repo.get_statistics()
        generated_exams = list(self.exams_dir.glob("*.json"))

        return {
            "question_count": question_stats["total"],
            "regular_question_count": question_stats["total"],
            "exam_count": len(generated_exams),
            "generated_exam_count": len(generated_exams),
            "past_exam_count": past_exam_stats["exam_count"],
            "past_exam_question_count": past_exam_stats["question_count"],
            "past_exam_answered_count": past_exam_stats["answered_question_count"],
            "difficulty": question_stats["by_difficulty"],
            "validated": question_stats["validated"],
            "pending_review_count": max(question_stats["total"] - question_stats["validated"], 0),
            "by_topic": question_stats["by_topic"],
        }

    def list_questions(
        self,
        validated_only: bool = False,
        exam_track: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """List general-bank questions while tolerating repository signature drift."""
        supported_params = signature(self.question_repo.list_all).parameters

        exam_track_enum = None
        kwargs: dict = {"limit": limit}
        if "validated_only" in supported_params:
            kwargs["validated_only"] = validated_only

        if exam_track:
            exam_track_enum = ExamTrack(exam_track)
            if "exam_track" in supported_params:
                kwargs["exam_track"] = exam_track_enum

        questions = self.question_repo.list_all(**kwargs)

        if validated_only and "validated_only" not in supported_params:
            questions = [question for question in questions if getattr(question, "is_validated", False)]

        if exam_track_enum and "exam_track" not in supported_params:
            questions = [question for question in questions if getattr(question, "exam_track", None) == exam_track_enum]

        return [question.to_dict() for question in questions]


_query_service: QuestionBankQueryService | None = None


def get_question_bank_query_service() -> QuestionBankQueryService:
    """Return singleton query service for Streamlit read paths."""
    global _query_service
    if _query_service is None:
        _query_service = QuestionBankQueryService()
    return _query_service
