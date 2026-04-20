"""Application service for duplicate and similar question warnings."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from src.domain.entities.question_draft import QuestionDraftStatus
from src.infrastructure.persistence.sqlite_question_draft_repo import get_question_draft_repository
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository


class QuestionSimilarityService:
    """Provide lightweight similarity checks against bank questions and active drafts."""

    def __init__(self):
        self.question_repo = get_question_repository()
        self.draft_repo = get_question_draft_repository()

    def build_corpus(self) -> list[dict]:
        """Build a comparison corpus from the formal bank and active drafts."""
        corpus: list[dict] = []

        for question in self.question_repo.list_all(limit=500):
            corpus.append(
                {
                    "id": question.id,
                    "source_type": "bank",
                    "question_text": question.question_text,
                    "normalized_text": self._normalize(question.question_text),
                    "difficulty": question.difficulty.value,
                    "exam_track": question.exam_track.value if question.exam_track else None,
                }
            )

        for draft in self.draft_repo.list_all(status=QuestionDraftStatus.DRAFT, limit=500):
            corpus.append(
                {
                    "id": draft.id,
                    "source_type": "draft",
                    "question_text": draft.question.question_text,
                    "normalized_text": self._normalize(draft.question.question_text),
                    "difficulty": draft.question.difficulty.value,
                    "exam_track": draft.question.exam_track.value if draft.question.exam_track else None,
                }
            )

        return corpus

    def find_similar(
        self,
        question_text: str,
        threshold: float = 0.78,
        limit: int = 3,
        corpus: list[dict] | None = None,
        exclude_ids: set[str] | None = None,
    ) -> list[dict]:
        """Return the top similar questions above the configured threshold."""
        normalized_target = self._normalize(question_text)
        if len(normalized_target) < 8:
            return []

        excluded = exclude_ids or set()
        matches: list[dict] = []
        for entry in corpus or self.build_corpus():
            if entry["id"] in excluded:
                continue

            similarity = self._score(normalized_target, entry["normalized_text"])
            if similarity < threshold:
                continue

            matches.append(
                {
                    "id": entry["id"],
                    "source_type": entry["source_type"],
                    "question_text": entry["question_text"],
                    "difficulty": entry["difficulty"],
                    "exam_track": entry["exam_track"],
                    "similarity": similarity,
                }
            )

        matches.sort(key=lambda item: item["similarity"], reverse=True)
        return matches[:limit]

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
        return normalized.strip()

    @staticmethod
    def _score(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0

        ratio = SequenceMatcher(None, left, right).ratio()
        if left in right or right in left:
            ratio = max(ratio, 0.92)
        return ratio


_service: QuestionSimilarityService | None = None


def get_question_similarity_service() -> QuestionSimilarityService:
    """Return singleton similarity workflow service."""
    global _service
    if _service is None:
        _service = QuestionSimilarityService()
    return _service
