"""Past exam repository interface.

Domain-facing contract for storing extracted past exams, structured question
records, and derived concepts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.past_exam import Concept, PastExam, PastExamQuestion


class IPastExamRepository(ABC):
    """Persistence contract for past exam extraction artifacts."""

    @abstractmethod
    def save_exam(self, past_exam: PastExam) -> str:
        """Create or update a past exam aggregate."""

    @abstractmethod
    def get_exam(self, exam_id: str) -> Optional[PastExam]:
        """Load a past exam aggregate by ID."""

    @abstractmethod
    def get_exam_by_doc_id(self, source_doc_id: str) -> Optional[PastExam]:
        """Load a past exam aggregate by ingested asset-aware doc_id."""

    @abstractmethod
    def save_questions(self, past_exam_id: str, questions: list[PastExamQuestion]) -> int:
        """Upsert normalized or classified past exam questions."""

    @abstractmethod
    def list_questions(self, past_exam_id: str) -> list[PastExamQuestion]:
        """List normalized/classified questions for one extracted exam."""

    @abstractmethod
    def list_exam_catalog(self, limit: int = 20) -> list[dict]:
        """List past exam summary rows for dashboard / management views."""

    @abstractmethod
    def get_statistics(self) -> dict[str, int]:
        """Return aggregate counts for imported past exams and questions."""

    @abstractmethod
    def upsert_concepts(self, concepts: list[Concept]) -> int:
        """Upsert concept catalog entries discovered during classification."""
