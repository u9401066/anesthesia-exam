"""Question draft repository interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.question_draft import QuestionDraft, QuestionDraftStatus, QuestionDraftVersion


class IQuestionDraftRepository(ABC):
    """Persistence contract for draft questions."""

    @abstractmethod
    def save(
        self,
        draft: QuestionDraft,
        actor_name: str = "system",
        reason: str | None = None,
        action: str | None = None,
    ) -> str:
        """Create or update a draft question."""

    @abstractmethod
    def get_by_id(self, draft_id: str) -> Optional[QuestionDraft]:
        """Load one draft by ID."""

    @abstractmethod
    def list_all(
        self,
        status: Optional[QuestionDraftStatus] = None,
        starred_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[QuestionDraft]:
        """List draft questions for the authoring UI."""

    @abstractmethod
    def bulk_update(
        self,
        draft_ids: list[str],
        difficulty: Optional[str] = None,
        topics: Optional[list[str]] = None,
        exam_track: Optional[str] = None,
        is_validated: Optional[bool] = None,
        is_starred: Optional[bool] = None,
        notes: Optional[str] = None,
        actor_name: str = "streamlit-admin",
        reason: str | None = None,
    ) -> int:
        """Apply one batch edit to multiple drafts."""

    @abstractmethod
    def archive(
        self,
        draft_ids: list[str],
        actor_name: str = "streamlit-admin",
        reason: str | None = None,
    ) -> int:
        """Archive selected drafts."""

    @abstractmethod
    def mark_promoted(
        self,
        draft_id: str,
        question_id: str,
        actor_name: str = "streamlit-admin",
        reason: str | None = None,
    ) -> bool:
        """Mark a draft as promoted into the formal question bank."""

    @abstractmethod
    def get_history(self, draft_id: str, limit: int = 20) -> list[QuestionDraftVersion]:
        """Load version history for one draft."""

    @abstractmethod
    def get_statistics(self) -> dict:
        """Return aggregate stats for the draft box."""
