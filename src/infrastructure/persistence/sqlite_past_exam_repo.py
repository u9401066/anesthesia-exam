"""SQLite repository for extracted past exams."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.domain.entities.past_exam import Concept, PastExam, PastExamQuestion, QuestionPattern
from src.domain.repositories.past_exam_repository import IPastExamRepository
from src.infrastructure.persistence.database import get_connection, init_database


class SQLitePastExamRepository(IPastExamRepository):
    """Persist normalized/classified past exam artifacts into SQLite."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path
        init_database(db_path)

    def save_exam(self, past_exam: PastExam) -> str:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO past_exams (
                    id, exam_year, exam_name, total_questions, source_pdf, source_doc_id,
                    imported_at, imported_by, is_ocr_done, is_parsed, is_classified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    exam_year = excluded.exam_year,
                    exam_name = excluded.exam_name,
                    total_questions = excluded.total_questions,
                    source_pdf = excluded.source_pdf,
                    source_doc_id = excluded.source_doc_id,
                    imported_at = excluded.imported_at,
                    imported_by = excluded.imported_by,
                    is_ocr_done = excluded.is_ocr_done,
                    is_parsed = excluded.is_parsed,
                    is_classified = excluded.is_classified
                """,
                (
                    past_exam.id,
                    past_exam.exam_year,
                    past_exam.exam_name,
                    past_exam.total_questions,
                    past_exam.source_pdf,
                    past_exam.source_doc_id,
                    past_exam.imported_at.isoformat(),
                    past_exam.imported_by,
                    1 if past_exam.is_ocr_done else 0,
                    1 if past_exam.is_parsed else 0,
                    1 if past_exam.is_classified else 0,
                ),
            )
            conn.commit()
        return past_exam.id

    def get_exam(self, exam_id: str) -> Optional[PastExam]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM past_exams WHERE id = ?", (exam_id,))
            row = cursor.fetchone()
            if row is None:
                return None

        exam = self._row_to_past_exam(row)
        exam.questions = self.list_questions(exam.id)
        exam.total_questions = len(exam.questions)
        return exam

    def get_exam_by_doc_id(self, source_doc_id: str) -> Optional[PastExam]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM past_exams WHERE source_doc_id = ? ORDER BY imported_at DESC LIMIT 1",
                (source_doc_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

        exam = self._row_to_past_exam(row)
        exam.questions = self.list_questions(exam.id)
        exam.total_questions = len(exam.questions)
        return exam

    def save_questions(self, past_exam_id: str, questions: list[PastExamQuestion]) -> int:
        if not questions:
            return 0

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            keep_ids = [question.id for question in questions]
            placeholders = ", ".join("?" for _ in keep_ids)
            cursor.execute(
                f"DELETE FROM past_exam_questions WHERE past_exam_id = ? AND id NOT IN ({placeholders})",
                [past_exam_id, *keep_ids],
            )
            for question in questions:
                question.past_exam_id = past_exam_id
                cursor.execute(
                    """
                    INSERT INTO past_exam_questions (
                        id, past_exam_id, exam_year, exam_name, question_number,
                        question_text, options, correct_answer, explanation,
                        concepts, concept_names, pattern, difficulty, bloom_level,
                        topics, source_doc_id, source_page, raw_text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        past_exam_id = excluded.past_exam_id,
                        exam_year = excluded.exam_year,
                        exam_name = excluded.exam_name,
                        question_number = excluded.question_number,
                        question_text = excluded.question_text,
                        options = excluded.options,
                        correct_answer = excluded.correct_answer,
                        explanation = excluded.explanation,
                        concepts = excluded.concepts,
                        concept_names = excluded.concept_names,
                        pattern = excluded.pattern,
                        difficulty = excluded.difficulty,
                        bloom_level = excluded.bloom_level,
                        topics = excluded.topics,
                        source_doc_id = excluded.source_doc_id,
                        source_page = excluded.source_page,
                        raw_text = excluded.raw_text,
                        created_at = excluded.created_at
                    """,
                    (
                        question.id,
                        past_exam_id,
                        question.exam_year,
                        question.exam_name,
                        question.question_number,
                        question.question_text,
                        json.dumps(question.options, ensure_ascii=False),
                        question.correct_answer,
                        question.explanation,
                        json.dumps(question.concepts, ensure_ascii=False),
                        json.dumps(question.concept_names, ensure_ascii=False),
                        question.pattern.value,
                        question.difficulty,
                        question.bloom_level,
                        json.dumps(question.topics, ensure_ascii=False),
                        question.source_doc_id,
                        question.source_page,
                        question.raw_text,
                        question.created_at.isoformat(),
                    ),
                )

            cursor.execute(
                "UPDATE past_exams SET total_questions = ?, is_parsed = 1 WHERE id = ?",
                (len(questions), past_exam_id),
            )
            conn.commit()
        return len(questions)

    def list_questions(self, past_exam_id: str) -> list[PastExamQuestion]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM past_exam_questions WHERE past_exam_id = ? ORDER BY question_number ASC",
                (past_exam_id,),
            )
            rows = cursor.fetchall()
        return [self._row_to_question(row) for row in rows]

    def upsert_concepts(self, concepts: list[Concept]) -> int:
        if not concepts:
            return 0

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            for concept in concepts:
                cursor.execute(
                    """
                    INSERT INTO concepts (id, name, category, subcategory, keywords, related_concepts)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        category = excluded.category,
                        subcategory = excluded.subcategory,
                        keywords = excluded.keywords,
                        related_concepts = excluded.related_concepts
                    """,
                    (
                        concept.id,
                        concept.name,
                        concept.category,
                        concept.subcategory,
                        json.dumps(concept.keywords, ensure_ascii=False),
                        json.dumps(concept.related_concepts, ensure_ascii=False),
                    ),
                )
            conn.commit()
        return len(concepts)

    def _row_to_past_exam(self, row) -> PastExam:
        return PastExam(
            id=row["id"],
            exam_year=row["exam_year"],
            exam_name=row["exam_name"],
            total_questions=row["total_questions"] or 0,
            source_pdf=row["source_pdf"] or "",
            source_doc_id=row["source_doc_id"],
            imported_at=datetime.fromisoformat(row["imported_at"]) if row["imported_at"] else datetime.now(),
            imported_by=row["imported_by"] or "agent",
            is_ocr_done=bool(row["is_ocr_done"]),
            is_parsed=bool(row["is_parsed"]),
            is_classified=bool(row["is_classified"]),
        )

    def _row_to_question(self, row) -> PastExamQuestion:
        return PastExamQuestion(
            id=row["id"],
            past_exam_id=row["past_exam_id"],
            exam_year=row["exam_year"],
            exam_name=row["exam_name"] or "",
            question_number=row["question_number"] or 0,
            question_text=row["question_text"] or "",
            options=json.loads(row["options"] or "[]"),
            correct_answer=row["correct_answer"] or "",
            explanation=row["explanation"] or "",
            concepts=json.loads(row["concepts"] or "[]"),
            concept_names=json.loads(row["concept_names"] or "[]"),
            pattern=QuestionPattern(row["pattern"] or "direct_recall"),
            difficulty=row["difficulty"] or "medium",
            bloom_level=row["bloom_level"] or 1,
            topics=json.loads(row["topics"] or "[]"),
            source_doc_id=row["source_doc_id"],
            source_page=row["source_page"],
            raw_text=row["raw_text"] or "",
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
        )


_past_exam_repo_singleton: SQLitePastExamRepository | None = None


def get_past_exam_repository(db_path: Path | None = None) -> SQLitePastExamRepository:
    """Return a lazily initialized singleton repository."""
    global _past_exam_repo_singleton
    if db_path is not None:
        return SQLitePastExamRepository(db_path=db_path)
    if _past_exam_repo_singleton is None:
        _past_exam_repo_singleton = SQLitePastExamRepository()
    return _past_exam_repo_singleton
