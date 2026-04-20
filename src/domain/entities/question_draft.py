"""Question draft entity for the authoring workflow."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from src.domain.entities.question import Question


class QuestionDraftStatus(str, Enum):
    """Lifecycle status for a draft question."""

    DRAFT = "draft"
    PROMOTED = "promoted"
    ARCHIVED = "archived"


class SourceConfidence(str, Enum):
    """User-facing source confidence tiers for draft questions."""

    PRECISE = "precise"
    CONTEXTUAL = "contextual"
    NONE = "none"


class DraftChecklistStatus(str, Enum):
    """Checklist state for one QA dimension."""

    PENDING = "pending"
    PASS = "pass"
    REVISE = "revise"


class DraftQAStatus(str, Enum):
    """Overall QA readiness for one draft."""

    PENDING = "pending"
    READY = "ready"
    NEEDS_REVISION = "needs_revision"


@dataclass
class DraftTemplateReference:
    """Reference to a historical-question-backed authoring template."""

    template_id: str = ""
    label: str = ""
    pattern: str = ""
    pattern_label: str = ""
    source_exam_id: str | None = None
    source_question_id: str | None = None
    source_exam_name: str = ""
    source_exam_year: int = 0
    source_question_number: int = 0
    option_count: int = 4
    reference_question_text: str = ""
    stem_scaffold: str = ""
    topics: list[str] = field(default_factory=list)
    difficulty: str = "medium"
    bloom_level: int = 1

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "label": self.label,
            "pattern": self.pattern,
            "pattern_label": self.pattern_label,
            "source_exam_id": self.source_exam_id,
            "source_question_id": self.source_question_id,
            "source_exam_name": self.source_exam_name,
            "source_exam_year": self.source_exam_year,
            "source_question_number": self.source_question_number,
            "option_count": self.option_count,
            "reference_question_text": self.reference_question_text,
            "stem_scaffold": self.stem_scaffold,
            "topics": list(self.topics),
            "difficulty": self.difficulty,
            "bloom_level": self.bloom_level,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> Optional["DraftTemplateReference"]:
        if not data:
            return None
        return cls(
            template_id=data.get("template_id", ""),
            label=data.get("label", ""),
            pattern=data.get("pattern", ""),
            pattern_label=data.get("pattern_label", ""),
            source_exam_id=data.get("source_exam_id"),
            source_question_id=data.get("source_question_id"),
            source_exam_name=data.get("source_exam_name", ""),
            source_exam_year=int(data.get("source_exam_year", 0) or 0),
            source_question_number=int(data.get("source_question_number", 0) or 0),
            option_count=int(data.get("option_count", 4) or 4),
            reference_question_text=data.get("reference_question_text", ""),
            stem_scaffold=data.get("stem_scaffold", ""),
            topics=list(data.get("topics", [])),
            difficulty=data.get("difficulty", "medium"),
            bloom_level=int(data.get("bloom_level", 1) or 1),
        )


@dataclass
class DraftBlueprint:
    """Authoring blueprint derived from historical patterns or current review context."""

    pattern: str = ""
    pattern_label: str = ""
    difficulty: str = "medium"
    bloom_level: int = 1
    target_topics: list[str] = field(default_factory=list)
    reference_concepts: list[str] = field(default_factory=list)
    recommended_rules: list[str] = field(default_factory=list)
    sample_source_refs: list[str] = field(default_factory=list)
    historical_pattern_distribution: dict[str, int] = field(default_factory=dict)
    source_exam_years: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "pattern_label": self.pattern_label,
            "difficulty": self.difficulty,
            "bloom_level": self.bloom_level,
            "target_topics": list(self.target_topics),
            "reference_concepts": list(self.reference_concepts),
            "recommended_rules": list(self.recommended_rules),
            "sample_source_refs": list(self.sample_source_refs),
            "historical_pattern_distribution": dict(self.historical_pattern_distribution),
            "source_exam_years": list(self.source_exam_years),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "DraftBlueprint":
        if not data:
            return cls()
        return cls(
            pattern=data.get("pattern", ""),
            pattern_label=data.get("pattern_label", ""),
            difficulty=data.get("difficulty", "medium"),
            bloom_level=int(data.get("bloom_level", 1) or 1),
            target_topics=list(data.get("target_topics", [])),
            reference_concepts=list(data.get("reference_concepts", [])),
            recommended_rules=list(data.get("recommended_rules", [])),
            sample_source_refs=list(data.get("sample_source_refs", [])),
            historical_pattern_distribution=dict(data.get("historical_pattern_distribution", {})),
            source_exam_years=[int(year) for year in data.get("source_exam_years", [])],
        )


@dataclass
class DraftQAMetadata:
    """QA checklist metadata used by the authoring workflow."""

    overall_status: DraftQAStatus = DraftQAStatus.PENDING
    stem_quality: DraftChecklistStatus = DraftChecklistStatus.PENDING
    option_quality: DraftChecklistStatus = DraftChecklistStatus.PENDING
    answer_alignment: DraftChecklistStatus = DraftChecklistStatus.PENDING
    source_alignment: DraftChecklistStatus = DraftChecklistStatus.PENDING
    explanation_quality: DraftChecklistStatus = DraftChecklistStatus.PENDING
    review_notes: str = ""
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    similarity_warning_count: int = 0

    def to_dict(self) -> dict:
        return {
            "overall_status": self.overall_status.value,
            "stem_quality": self.stem_quality.value,
            "option_quality": self.option_quality.value,
            "answer_alignment": self.answer_alignment.value,
            "source_alignment": self.source_alignment.value,
            "explanation_quality": self.explanation_quality.value,
            "review_notes": self.review_notes,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "similarity_warning_count": self.similarity_warning_count,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "DraftQAMetadata":
        if not data:
            return cls()
        return cls(
            overall_status=DraftQAStatus(data.get("overall_status", DraftQAStatus.PENDING.value)),
            stem_quality=DraftChecklistStatus(data.get("stem_quality", DraftChecklistStatus.PENDING.value)),
            option_quality=DraftChecklistStatus(data.get("option_quality", DraftChecklistStatus.PENDING.value)),
            answer_alignment=DraftChecklistStatus(
                data.get("answer_alignment", DraftChecklistStatus.PENDING.value)
            ),
            source_alignment=DraftChecklistStatus(
                data.get("source_alignment", DraftChecklistStatus.PENDING.value)
            ),
            explanation_quality=DraftChecklistStatus(
                data.get("explanation_quality", DraftChecklistStatus.PENDING.value)
            ),
            review_notes=data.get("review_notes", ""),
            reviewer=data.get("reviewer"),
            reviewed_at=datetime.fromisoformat(data["reviewed_at"]) if data.get("reviewed_at") else None,
            similarity_warning_count=int(data.get("similarity_warning_count", 0) or 0),
        )


def classify_source_confidence(question: Question) -> SourceConfidence:
    """Map question source structure to a simple confidence tier."""
    source = question.source
    if not source:
        return SourceConfidence.NONE

    if source.stem_source or source.answer_source or source.explanation_sources:
        return SourceConfidence.PRECISE

    if source.document or source.page or source.original_text:
        return SourceConfidence.CONTEXTUAL

    return SourceConfidence.NONE


@dataclass
class QuestionDraft:
    """Persistent draft wrapper around a question entity."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    question: Question = field(default_factory=Question)
    status: QuestionDraftStatus = QuestionDraftStatus.DRAFT
    source_confidence: SourceConfidence = SourceConfidence.NONE
    is_starred: bool = False
    notes: str = ""
    origin: str = "generated_review"
    template_data: DraftTemplateReference | None = None
    blueprint_data: DraftBlueprint = field(default_factory=DraftBlueprint)
    qa_metadata: DraftQAMetadata = field(default_factory=DraftQAMetadata)
    promoted_question_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question.to_dict(),
            "status": self.status.value,
            "source_confidence": self.source_confidence.value,
            "is_starred": self.is_starred,
            "notes": self.notes,
            "origin": self.origin,
            "template_data": self.template_data.to_dict() if self.template_data else None,
            "blueprint_data": self.blueprint_data.to_dict(),
            "qa_metadata": self.qa_metadata.to_dict(),
            "promoted_question_id": self.promoted_question_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuestionDraft":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            question=Question.from_dict(data.get("question", {})),
            status=QuestionDraftStatus(data.get("status", "draft")),
            source_confidence=SourceConfidence(data.get("source_confidence", "none")),
            is_starred=bool(data.get("is_starred", False)),
            notes=data.get("notes", ""),
            origin=data.get("origin", "generated_review"),
            template_data=DraftTemplateReference.from_dict(data.get("template_data")),
            blueprint_data=DraftBlueprint.from_dict(data.get("blueprint_data")),
            qa_metadata=DraftQAMetadata.from_dict(data.get("qa_metadata")),
            promoted_question_id=data.get("promoted_question_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )


@dataclass
class QuestionDraftVersion:
    """Immutable snapshot entry for draft change history."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    draft_id: str = ""
    version_number: int = 0
    action: str = "updated"
    actor_name: str = "system"
    reason: str = ""
    snapshot_data: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "draft_id": self.draft_id,
            "version_number": self.version_number,
            "action": self.action,
            "actor_name": self.actor_name,
            "reason": self.reason,
            "snapshot_data": self.snapshot_data,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuestionDraftVersion":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            draft_id=data.get("draft_id", ""),
            version_number=int(data.get("version_number", 0) or 0),
            action=data.get("action", "updated"),
            actor_name=data.get("actor_name", "system"),
            reason=data.get("reason", ""),
            snapshot_data=dict(data.get("snapshot_data", {})),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        )
