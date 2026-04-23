"""SQLite repository for draft questions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.domain.entities.question import Difficulty, ExamTrack, Question
from src.domain.entities.question_draft import (
    DraftBlueprint,
    DraftQAMetadata,
    DraftTemplateReference,
    QuestionDraft,
    QuestionDraftStatus,
    QuestionDraftVersion,
    SourceConfidence,
    classify_source_confidence,
)
from src.domain.repositories.question_draft_repository import IQuestionDraftRepository
from src.infrastructure.persistence.database import begin_immediate_transaction, get_connection, init_database


class SQLiteQuestionDraftRepository(IQuestionDraftRepository):
    """SQLite-backed draft question storage."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path
        init_database(db_path)

    def save(
        self,
        draft: QuestionDraft,
        actor_name: str = "system",
        reason: str | None = None,
        action: str | None = None,
    ) -> str:
        with get_connection(self.db_path) as conn:
            begin_immediate_transaction(conn)
            return self.save_with_connection(
                conn,
                draft,
                actor_name=actor_name,
                reason=reason,
                action=action,
                commit=True,
            )

    def save_with_connection(
        self,
        conn,
        draft: QuestionDraft,
        actor_name: str = "system",
        reason: str | None = None,
        action: str | None = None,
        commit: bool = False,
    ) -> str:
        draft.source_confidence = classify_source_confidence(draft.question)
        now_dt = datetime.now()
        now = now_dt.isoformat()
        draft.updated_at = now_dt

        cursor = conn.cursor()
        cursor.execute("SELECT created_at FROM question_drafts WHERE id = ?", (draft.id,))
        existing_row = cursor.fetchone()
        created_at = existing_row["created_at"] if existing_row and existing_row["created_at"] else draft.created_at.isoformat()
        draft.created_at = datetime.fromisoformat(created_at) if isinstance(created_at, str) else draft.created_at
        cursor.execute(
            """
            INSERT INTO question_drafts (
                id, question_data, source_confidence, status,
                is_starred, notes, origin, template_data,
                blueprint_data, qa_metadata, promoted_question_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question_data = excluded.question_data,
                source_confidence = excluded.source_confidence,
                status = excluded.status,
                is_starred = excluded.is_starred,
                notes = excluded.notes,
                origin = excluded.origin,
                template_data = excluded.template_data,
                blueprint_data = excluded.blueprint_data,
                qa_metadata = excluded.qa_metadata,
                promoted_question_id = excluded.promoted_question_id,
                updated_at = excluded.updated_at
            """,
            (
                draft.id,
                json.dumps(draft.question.to_dict(), ensure_ascii=False),
                draft.source_confidence.value,
                draft.status.value,
                1 if draft.is_starred else 0,
                draft.notes,
                draft.origin,
                json.dumps(draft.template_data.to_dict(), ensure_ascii=False) if draft.template_data else None,
                json.dumps(draft.blueprint_data.to_dict(), ensure_ascii=False),
                json.dumps(draft.qa_metadata.to_dict(), ensure_ascii=False),
                draft.promoted_question_id,
                created_at,
                now,
            ),
        )
        self._add_version(
            conn,
            draft=draft,
            actor_name=actor_name,
            reason=reason,
            action=action or ("created" if existing_row is None else "updated"),
            created_at=now,
        )
        if commit:
            conn.commit()
        return draft.id

    def get_by_id(self, draft_id: str) -> Optional[QuestionDraft]:
        with get_connection(self.db_path) as conn:
            return self._get_by_id_with_connection(conn, draft_id)

    def list_all(
        self,
        status: Optional[QuestionDraftStatus] = None,
        starred_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[QuestionDraft]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM question_drafts WHERE 1=1"
            params: list = []

            if status:
                query += " AND status = ?"
                params.append(status.value)

            if starred_only:
                query += " AND is_starred = 1"

            query += " ORDER BY is_starred DESC, updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cursor.execute(query, params)
            return [self._row_to_draft(row) for row in cursor.fetchall()]

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
        if not draft_ids:
            return 0

        parsed_difficulty = self._parse_difficulty(difficulty) if difficulty is not None else None
        parsed_exam_track = self._parse_exam_track(exam_track) if exam_track is not None else None

        updated = 0
        for draft_id in draft_ids:
            draft = self.get_by_id(draft_id)
            if draft is None:
                continue

            question = draft.question
            if parsed_difficulty is not None:
                question.difficulty = parsed_difficulty
            if topics is not None:
                question.topics = topics
            if exam_track is not None:
                question.exam_track = parsed_exam_track
            if is_validated is not None:
                question.is_validated = is_validated
            if is_starred is not None:
                draft.is_starred = is_starred
            if notes is not None:
                draft.notes = notes

            draft.question = question
            self.save(
                draft,
                actor_name=actor_name,
                reason=reason or "Bulk update from draft box",
                action="batch_updated",
            )
            updated += 1

        return updated

    def archive(
        self,
        draft_ids: list[str],
        actor_name: str = "streamlit-admin",
        reason: str | None = None,
    ) -> int:
        if not draft_ids:
            return 0

        archived = 0
        for draft_id in draft_ids:
            draft = self.get_by_id(draft_id)
            if draft is None or draft.status == QuestionDraftStatus.ARCHIVED:
                continue
            draft.status = QuestionDraftStatus.ARCHIVED
            self.save(
                draft,
                actor_name=actor_name,
                reason=reason or "Archived from draft box",
                action="archived",
            )
            archived += 1
        return archived

    def mark_promoted(
        self,
        draft_id: str,
        question_id: str,
        actor_name: str = "streamlit-admin",
        reason: str | None = None,
    ) -> bool:
        with get_connection(self.db_path) as conn:
            begin_immediate_transaction(conn)
            result = self.mark_promoted_with_connection(
                conn,
                draft_id,
                question_id,
                actor_name=actor_name,
                reason=reason,
            )
            conn.commit()
            return result

    def mark_promoted_with_connection(
        self,
        conn,
        draft_id: str,
        question_id: str,
        actor_name: str = "streamlit-admin",
        reason: str | None = None,
    ) -> bool:
        draft = self._get_by_id_with_connection(conn, draft_id)
        if draft is None:
            return False

        draft.status = QuestionDraftStatus.PROMOTED
        draft.promoted_question_id = question_id
        self.save_with_connection(
            conn,
            draft,
            actor_name=actor_name,
            reason=reason or f"Promoted to formal bank as {question_id}",
            action="promoted",
            commit=False,
        )
        return True

    def get_history(self, draft_id: str, limit: int = 20) -> list[QuestionDraftVersion]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM question_draft_versions
                WHERE draft_id = ?
                ORDER BY version_number DESC
                LIMIT ?
                """,
                (draft_id, limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_version(row) for row in rows]

    def get_statistics(self) -> dict:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM question_drafts")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT status, COUNT(*) FROM question_drafts GROUP BY status")
            by_status = dict(cursor.fetchall())

            cursor.execute("SELECT COUNT(*) FROM question_drafts WHERE is_starred = 1")
            starred = cursor.fetchone()[0]

            cursor.execute("SELECT source_confidence, COUNT(*) FROM question_drafts GROUP BY source_confidence")
            by_source_confidence = dict(cursor.fetchall())

            return {
                "total": total,
                "draft": by_status.get(QuestionDraftStatus.DRAFT.value, 0),
                "promoted": by_status.get(QuestionDraftStatus.PROMOTED.value, 0),
                "archived": by_status.get(QuestionDraftStatus.ARCHIVED.value, 0),
                "starred": starred,
                "by_source_confidence": by_source_confidence,
            }

    def _row_to_draft(self, row) -> QuestionDraft:
        row_keys = set(row.keys())
        question = Question.from_dict(json.loads(row["question_data"]))
        return QuestionDraft(
            id=row["id"],
            question=question,
            status=QuestionDraftStatus(row["status"] or QuestionDraftStatus.DRAFT.value),
            source_confidence=SourceConfidence(row["source_confidence"] or SourceConfidence.NONE.value),
            is_starred=bool(row["is_starred"]),
            notes=row["notes"] or "",
            origin=row["origin"] or "generated_review",
            template_data=DraftTemplateReference.from_dict(
                json.loads(row["template_data"]) if "template_data" in row_keys and row["template_data"] else None
            ),
            blueprint_data=DraftBlueprint.from_dict(
                json.loads(row["blueprint_data"]) if "blueprint_data" in row_keys and row["blueprint_data"] else None
            ),
            qa_metadata=DraftQAMetadata.from_dict(
                json.loads(row["qa_metadata"]) if "qa_metadata" in row_keys and row["qa_metadata"] else None
            ),
            promoted_question_id=row["promoted_question_id"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
        )

    def _get_by_id_with_connection(self, conn, draft_id: str) -> Optional[QuestionDraft]:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM question_drafts WHERE id = ?", (draft_id,))
        row = cursor.fetchone()
        return self._row_to_draft(row) if row else None

    def _add_version(
        self,
        conn,
        draft: QuestionDraft,
        actor_name: str,
        reason: str | None,
        action: str,
        created_at: str,
    ) -> None:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(version_number), 0) FROM question_draft_versions WHERE draft_id = ?",
            (draft.id,),
        )
        next_version = int(cursor.fetchone()[0]) + 1
        version_entry = QuestionDraftVersion(
            draft_id=draft.id,
            version_number=next_version,
            action=action,
            actor_name=actor_name,
            reason=reason or "",
            snapshot_data=draft.to_dict(),
            created_at=datetime.fromisoformat(created_at),
        )
        cursor.execute(
            """
            INSERT INTO question_draft_versions (
                id, draft_id, version_number, action, actor_name,
                reason, snapshot_data, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_entry.id,
                version_entry.draft_id,
                version_entry.version_number,
                version_entry.action,
                version_entry.actor_name,
                version_entry.reason,
                json.dumps(version_entry.snapshot_data, ensure_ascii=False),
                version_entry.created_at.isoformat(),
            ),
        )

    def _row_to_version(self, row) -> QuestionDraftVersion:
        return QuestionDraftVersion(
            id=row["id"],
            draft_id=row["draft_id"],
            version_number=int(row["version_number"] or 0),
            action=row["action"] or "updated",
            actor_name=row["actor_name"] or "system",
            reason=row["reason"] or "",
            snapshot_data=json.loads(row["snapshot_data"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
        )

    def _parse_difficulty(self, difficulty: str) -> Difficulty:
        try:
            return Difficulty(difficulty)
        except ValueError as exc:
            raise ValueError(f"Unsupported draft difficulty: {difficulty}") from exc

    def _parse_exam_track(self, exam_track: str) -> ExamTrack | None:
        if not exam_track:
            return None
        try:
            return ExamTrack(exam_track)
        except ValueError as exc:
            raise ValueError(f"Unsupported draft exam_track: {exam_track}") from exc


_repository: SQLiteQuestionDraftRepository | None = None


def get_question_draft_repository() -> SQLiteQuestionDraftRepository:
    """Return singleton draft repository."""
    global _repository
    if _repository is None:
        _repository = SQLiteQuestionDraftRepository()
    return _repository
