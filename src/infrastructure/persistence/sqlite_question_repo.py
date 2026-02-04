"""
SQLite Question Repository - SQLite 題目儲存庫實作

實作 IQuestionRepository 介面，使用 SQLite 作為持久化層。
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.domain.entities.question import Question, Difficulty, QuestionType, Source
from src.domain.repositories.question_repository import IQuestionRepository
from src.domain.value_objects.audit import AuditEntry, AuditAction, ActorType
from src.infrastructure.persistence.database import get_connection, init_database


class SQLiteQuestionRepository(IQuestionRepository):
    """
    SQLite 題目儲存庫
    
    提供完整 CRUD + 審計追蹤功能。
    """
    
    def __init__(self, db_path: Path | None = None):
        """
        初始化儲存庫
        
        Args:
            db_path: 資料庫路徑，None 則使用預設路徑
        """
        self.db_path = db_path
        init_database(db_path)
    
    # ==================== Create ====================
    
    def save(
        self,
        question: Question,
        actor_type: ActorType = ActorType.AGENT,
        actor_name: str = "crush",
        generation_context: Optional[dict] = None,
    ) -> str:
        """儲存題目（新增或更新）"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 檢查是否已存在
            cursor.execute("SELECT id FROM questions WHERE id = ?", (question.id,))
            exists = cursor.fetchone() is not None
            
            if exists:
                # 更新
                return self._update_internal(conn, question, actor_type, actor_name, None)
            else:
                # 新增
                now = datetime.now().isoformat()
                
                cursor.execute("""
                    INSERT INTO questions (
                        id, question_text, options, correct_answer, explanation,
                        source, question_type, difficulty, topics, points,
                        image_path, created_at, created_by, updated_at,
                        is_deleted, is_validated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                """, (
                    question.id,
                    question.question_text,
                    json.dumps(question.options, ensure_ascii=False),
                    question.correct_answer,
                    question.explanation,
                    json.dumps(question.source.to_dict() if hasattr(question.source, 'to_dict') 
                              else self._source_to_dict(question.source), ensure_ascii=False) if question.source else None,
                    question.question_type.value,
                    question.difficulty.value,
                    json.dumps(question.topics, ensure_ascii=False),
                    question.points,
                    question.image_path,
                    question.created_at.isoformat() if isinstance(question.created_at, datetime) else now,
                    question.created_by,
                    now,
                ))
                
                # 記錄審計
                self._add_audit(
                    conn,
                    question_id=question.id,
                    action=AuditAction.CREATED,
                    actor_type=actor_type,
                    actor_name=actor_name,
                    generation_context=generation_context,
                )
                
                conn.commit()
                return question.id
    
    def _source_to_dict(self, source: Source | None) -> dict | None:
        """將 Source 轉為字典"""
        if source is None:
            return None
        return {
            "document": source.document,
            "page": source.page,
            "lines": source.lines,
            "original_text": source.original_text,
            "figure_caption": getattr(source, 'figure_caption', None),
        }
    
    # ==================== Read ====================
    
    def get_by_id(self, question_id: str) -> Optional[Question]:
        """根據 ID 取得題目"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM questions WHERE id = ? AND is_deleted = 0
            """, (question_id,))
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_question(row)
    
    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        difficulty: Optional[Difficulty] = None,
        question_type: Optional[QuestionType] = None,
        topic: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_by: Optional[str] = None,
    ) -> list[Question]:
        """列出題目（支援篩選）"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM questions WHERE is_deleted = 0"
            params: list = []
            
            if difficulty:
                query += " AND difficulty = ?"
                params.append(difficulty.value)
            
            if question_type:
                query += " AND question_type = ?"
                params.append(question_type.value)
            
            if topic:
                query += " AND topics LIKE ?"
                params.append(f"%{topic}%")
            
            if created_after:
                query += " AND created_at >= ?"
                params.append(created_after.isoformat())
            
            if created_by:
                query += " AND created_by = ?"
                params.append(created_by)
            
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_question(row) for row in rows]
    
    def count(
        self,
        difficulty: Optional[Difficulty] = None,
        question_type: Optional[QuestionType] = None,
    ) -> int:
        """統計題目數量"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = "SELECT COUNT(*) FROM questions WHERE is_deleted = 0"
            params: list = []
            
            if difficulty:
                query += " AND difficulty = ?"
                params.append(difficulty.value)
            
            if question_type:
                query += " AND question_type = ?"
                params.append(question_type.value)
            
            cursor.execute(query, params)
            return cursor.fetchone()[0]
    
    def search(self, keyword: str, limit: int = 20) -> list[Question]:
        """搜尋題目"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 使用 FTS5 搜尋
            cursor.execute("""
                SELECT q.* FROM questions q
                JOIN questions_fts fts ON q.id = fts.id
                WHERE questions_fts MATCH ? AND q.is_deleted = 0
                LIMIT ?
            """, (keyword, limit))
            
            rows = cursor.fetchall()
            return [self._row_to_question(row) for row in rows]
    
    # ==================== Update ====================
    
    def update(
        self,
        question: Question,
        actor_type: ActorType = ActorType.SKILL,
        actor_name: str = "unknown",
        reason: Optional[str] = None,
    ) -> bool:
        """更新題目"""
        with get_connection(self.db_path) as conn:
            result = self._update_internal(conn, question, actor_type, actor_name, reason)
            return result is not None
    
    def _update_internal(
        self,
        conn,
        question: Question,
        actor_type: ActorType,
        actor_name: str,
        reason: Optional[str],
    ) -> Optional[str]:
        """內部更新方法"""
        cursor = conn.cursor()
        
        # 取得舊版本以計算變更
        cursor.execute("SELECT * FROM questions WHERE id = ?", (question.id,))
        old_row = cursor.fetchone()
        
        if old_row is None:
            return None
        
        old_question = self._row_to_question(old_row)
        changes = self._calculate_changes(old_question, question)
        
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE questions SET
                question_text = ?,
                options = ?,
                correct_answer = ?,
                explanation = ?,
                source = ?,
                question_type = ?,
                difficulty = ?,
                topics = ?,
                points = ?,
                image_path = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            question.question_text,
            json.dumps(question.options, ensure_ascii=False),
            question.correct_answer,
            question.explanation,
            json.dumps(self._source_to_dict(question.source), ensure_ascii=False) if question.source else None,
            question.question_type.value,
            question.difficulty.value,
            json.dumps(question.topics, ensure_ascii=False),
            question.points,
            question.image_path,
            now,
            question.id,
        ))
        
        # 記錄審計
        if changes:
            self._add_audit(
                conn,
                question_id=question.id,
                action=AuditAction.UPDATED,
                actor_type=actor_type,
                actor_name=actor_name,
                changes=changes,
                reason=reason,
            )
        
        conn.commit()
        return question.id
    
    def _calculate_changes(self, old: Question, new: Question) -> dict:
        """計算變更內容"""
        changes = {}
        
        fields = ['question_text', 'options', 'correct_answer', 'explanation', 
                  'difficulty', 'topics', 'points']
        
        for field in fields:
            old_val = getattr(old, field)
            new_val = getattr(new, field)
            
            # 處理 Enum
            if hasattr(old_val, 'value'):
                old_val = old_val.value
            if hasattr(new_val, 'value'):
                new_val = new_val.value
            
            if old_val != new_val:
                changes[field] = {"old": old_val, "new": new_val}
        
        return changes
    
    # ==================== Delete ====================
    
    def delete(
        self,
        question_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_name: str = "unknown",
        reason: Optional[str] = None,
        soft_delete: bool = True,
    ) -> bool:
        """刪除題目"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            if soft_delete:
                cursor.execute("""
                    UPDATE questions SET is_deleted = 1, updated_at = ?
                    WHERE id = ? AND is_deleted = 0
                """, (datetime.now().isoformat(), question_id))
            else:
                cursor.execute("DELETE FROM questions WHERE id = ?", (question_id,))
            
            if cursor.rowcount == 0:
                return False
            
            # 記錄審計
            self._add_audit(
                conn,
                question_id=question_id,
                action=AuditAction.DELETED,
                actor_type=actor_type,
                actor_name=actor_name,
                reason=reason,
            )
            
            conn.commit()
            return True
    
    def restore(
        self,
        question_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_name: str = "unknown",
    ) -> bool:
        """還原已刪除的題目"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE questions SET is_deleted = 0, updated_at = ?
                WHERE id = ? AND is_deleted = 1
            """, (datetime.now().isoformat(), question_id))
            
            if cursor.rowcount == 0:
                return False
            
            # 記錄審計
            self._add_audit(
                conn,
                question_id=question_id,
                action=AuditAction.RESTORED,
                actor_type=actor_type,
                actor_name=actor_name,
            )
            
            conn.commit()
            return True
    
    # ==================== Audit ====================
    
    def get_audit_log(self, question_id: str, limit: int = 50) -> list[AuditEntry]:
        """取得題目的審計日誌"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM question_audits 
                WHERE question_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (question_id, limit))
            
            rows = cursor.fetchall()
            return [self._row_to_audit(row) for row in rows]
    
    def get_generation_context(self, question_id: str) -> Optional[dict]:
        """取得題目的生成上下文"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT generation_context FROM question_audits
                WHERE question_id = ? AND action = 'created' AND generation_context IS NOT NULL
                ORDER BY timestamp ASC
                LIMIT 1
            """, (question_id,))
            
            row = cursor.fetchone()
            if row is None or row[0] is None:
                return None
            
            return json.loads(row[0])
    
    def _add_audit(
        self,
        conn,
        question_id: str,
        action: AuditAction,
        actor_type: ActorType,
        actor_name: str,
        changes: Optional[dict] = None,
        reason: Optional[str] = None,
        generation_context: Optional[dict] = None,
    ):
        """新增審計記錄"""
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO question_audits (
                id, question_id, action, actor_type, actor_name,
                changes, reason, generation_context, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            question_id,
            action.value,
            actor_type.value,
            actor_name,
            json.dumps(changes, ensure_ascii=False) if changes else None,
            reason,
            json.dumps(generation_context, ensure_ascii=False) if generation_context else None,
            datetime.now().isoformat(),
        ))
    
    # ==================== Validation ====================
    
    def mark_validated(
        self,
        question_id: str,
        passed: bool,
        actor_name: str = "question-validator",
        notes: Optional[str] = None,
    ) -> bool:
        """標記題目驗證結果"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE questions SET 
                    is_validated = ?, 
                    validation_notes = ?,
                    updated_at = ?
                WHERE id = ? AND is_deleted = 0
            """, (1 if passed else 0, notes, datetime.now().isoformat(), question_id))
            
            if cursor.rowcount == 0:
                return False
            
            # 記錄審計
            self._add_audit(
                conn,
                question_id=question_id,
                action=AuditAction.VALIDATED if passed else AuditAction.REJECTED,
                actor_type=ActorType.SKILL,
                actor_name=actor_name,
                reason=notes,
            )
            
            conn.commit()
            return True
    
    # ==================== Statistics ====================
    
    def get_statistics(self) -> dict:
        """取得題庫統計"""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 總題數
            cursor.execute("SELECT COUNT(*) FROM questions WHERE is_deleted = 0")
            total = cursor.fetchone()[0]
            
            # 按難度統計
            cursor.execute("""
                SELECT difficulty, COUNT(*) 
                FROM questions WHERE is_deleted = 0
                GROUP BY difficulty
            """)
            by_difficulty = dict(cursor.fetchall())
            
            # 按題型統計
            cursor.execute("""
                SELECT question_type, COUNT(*) 
                FROM questions WHERE is_deleted = 0
                GROUP BY question_type
            """)
            by_type = dict(cursor.fetchall())
            
            # 已驗證數
            cursor.execute("""
                SELECT COUNT(*) FROM questions 
                WHERE is_deleted = 0 AND is_validated = 1
            """)
            validated = cursor.fetchone()[0]
            
            # 已刪除數
            cursor.execute("SELECT COUNT(*) FROM questions WHERE is_deleted = 1")
            deleted = cursor.fetchone()[0]
            
            # 近7天新增
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            cursor.execute("""
                SELECT COUNT(*) FROM questions 
                WHERE is_deleted = 0 AND created_at >= ?
            """, (seven_days_ago,))
            recent = cursor.fetchone()[0]
            
            # 按主題統計 (Top 10)
            cursor.execute("""
                SELECT topics FROM questions WHERE is_deleted = 0
            """)
            topic_counts: dict[str, int] = {}
            for row in cursor.fetchall():
                if row[0]:
                    topics = json.loads(row[0])
                    for topic in topics:
                        topic_counts[topic] = topic_counts.get(topic, 0) + 1
            
            # 取 Top 10
            by_topic = dict(sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10])
            
            return {
                "total": total,
                "by_difficulty": by_difficulty,
                "by_type": by_type,
                "by_topic": by_topic,
                "validated": validated,
                "deleted": deleted,
                "recent_7_days": recent,
            }
    
    # ==================== Helpers ====================
    
    def _row_to_question(self, row) -> Question:
        """將資料庫列轉為 Question 實體"""
        source = None
        if row["source"]:
            source_data = json.loads(row["source"])
            source = Source(
                document=source_data.get("document", ""),
                page=source_data.get("page"),
                lines=source_data.get("lines"),
                original_text=source_data.get("original_text"),
                figure_caption=source_data.get("figure_caption"),
            )
        
        return Question(
            id=row["id"],
            question_text=row["question_text"],
            options=json.loads(row["options"]) if row["options"] else [],
            correct_answer=row["correct_answer"],
            explanation=row["explanation"] or "",
            source=source,
            question_type=QuestionType(row["question_type"]) if row["question_type"] else QuestionType.SINGLE_CHOICE,
            difficulty=Difficulty(row["difficulty"]) if row["difficulty"] else Difficulty.MEDIUM,
            topics=json.loads(row["topics"]) if row["topics"] else [],
            points=row["points"] or 1,
            image_path=row["image_path"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            created_by=row["created_by"] or "agent",
        )
    
    def _row_to_audit(self, row) -> AuditEntry:
        """將資料庫列轉為 AuditEntry"""
        return AuditEntry(
            id=row["id"],
            question_id=row["question_id"],
            action=AuditAction(row["action"]),
            actor_type=ActorType(row["actor_type"]),
            actor_name=row["actor_name"],
            changes=json.loads(row["changes"]) if row["changes"] else None,
            reason=row["reason"],
            generation_context=json.loads(row["generation_context"]) if row["generation_context"] else None,
            timestamp=datetime.fromisoformat(row["timestamp"]) if row["timestamp"] else datetime.now(),
        )


# 建立全域實例
_repository: SQLiteQuestionRepository | None = None


def get_question_repository() -> SQLiteQuestionRepository:
    """取得題目儲存庫實例（單例）"""
    global _repository
    if _repository is None:
        _repository = SQLiteQuestionRepository()
    return _repository
