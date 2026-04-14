"""
SQLite Scope Request Repository - SQLite 出題需求儲存庫實作
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.domain.entities.scope_request import ScopeRequest, ScopeRequestStatus
from src.domain.repositories.scope_request_repository import IScopeRequestRepository
from src.infrastructure.persistence.database import get_connection, init_database


class SQLiteScopeRequestRepository(IScopeRequestRepository):
    """SQLite 出題需求儲存庫"""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path
        init_database(db_path)

    def save(self, request: ScopeRequest) -> str:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute(
                """
                INSERT INTO scope_requests (
                    id, topic, chapter, difficulty, exam_track,
                    reason, requested_by, status, target_count,
                    fulfilled_count, created_at, updated_at,
                    fulfilled_at, admin_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    topic = excluded.topic,
                    chapter = excluded.chapter,
                    difficulty = excluded.difficulty,
                    exam_track = excluded.exam_track,
                    reason = excluded.reason,
                    status = excluded.status,
                    target_count = excluded.target_count,
                    fulfilled_count = excluded.fulfilled_count,
                    updated_at = excluded.updated_at,
                    fulfilled_at = excluded.fulfilled_at,
                    admin_notes = excluded.admin_notes
                """,
                (
                    request.id,
                    request.topic,
                    request.chapter,
                    request.difficulty,
                    request.exam_track,
                    request.reason,
                    request.requested_by,
                    request.status.value,
                    request.target_count,
                    request.fulfilled_count,
                    request.created_at.isoformat(),
                    now,
                    request.fulfilled_at.isoformat() if request.fulfilled_at else None,
                    request.admin_notes,
                ),
            )
            conn.commit()
        return request.id

    def get_by_id(self, request_id: str) -> Optional[ScopeRequest]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scope_requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_scope_request(row)

    def list_all(
        self,
        status: Optional[ScopeRequestStatus] = None,
        topic: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScopeRequest]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM scope_requests WHERE 1=1"
            params: list = []

            if status:
                query += " AND status = ?"
                params.append(status.value)

            if topic:
                query += " AND topic LIKE ?"
                params.append(f"%{topic}%")

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            return [self._row_to_scope_request(row) for row in cursor.fetchall()]

    def update_status(
        self,
        request_id: str,
        new_status: ScopeRequestStatus,
        admin_notes: Optional[str] = None,
    ) -> bool:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            fulfilled_at = now if new_status == ScopeRequestStatus.FULFILLED else None

            if admin_notes is not None:
                cursor.execute(
                    """
                    UPDATE scope_requests
                    SET status = ?, updated_at = ?, fulfilled_at = COALESCE(?, fulfilled_at), admin_notes = ?
                    WHERE id = ?
                    """,
                    (new_status.value, now, fulfilled_at, admin_notes, request_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE scope_requests
                    SET status = ?, updated_at = ?, fulfilled_at = COALESCE(?, fulfilled_at)
                    WHERE id = ?
                    """,
                    (new_status.value, now, fulfilled_at, request_id),
                )

            if cursor.rowcount == 0:
                return False
            conn.commit()
            return True

    def increment_fulfilled(self, request_id: str, count: int = 1) -> bool:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute(
                """
                UPDATE scope_requests
                SET fulfilled_count = fulfilled_count + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (count, now, request_id),
            )

            if cursor.rowcount == 0:
                return False

            # 自動完成：若已達標則更新狀態
            cursor.execute(
                """
                UPDATE scope_requests
                SET status = 'fulfilled', fulfilled_at = ?
                WHERE id = ? AND fulfilled_count >= target_count AND status != 'fulfilled'
                """,
                (now, request_id),
            )

            conn.commit()
            return True

    def get_pending_requests(self) -> list[ScopeRequest]:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scope_requests
                WHERE status IN ('pending', 'approved', 'in_progress')
                ORDER BY created_at ASC
                """,
            )
            return [self._row_to_scope_request(row) for row in cursor.fetchall()]

    def get_statistics(self) -> dict:
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM scope_requests")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT status, COUNT(*) FROM scope_requests GROUP BY status")
            by_status = dict(cursor.fetchall())

            cursor.execute(
                """
                SELECT topic, COUNT(*) FROM scope_requests
                GROUP BY topic ORDER BY COUNT(*) DESC LIMIT 10
                """
            )
            by_topic = dict(cursor.fetchall())

            total_target = 0
            total_fulfilled = 0
            cursor.execute("SELECT target_count, fulfilled_count FROM scope_requests")
            for row in cursor.fetchall():
                total_target += row[0] or 0
                total_fulfilled += row[1] or 0

            return {
                "total": total,
                "by_status": by_status,
                "by_topic": by_topic,
                "total_target": total_target,
                "total_fulfilled": total_fulfilled,
            }

    def _row_to_scope_request(self, row) -> ScopeRequest:
        return ScopeRequest(
            id=row["id"],
            topic=row["topic"],
            chapter=row["chapter"],
            difficulty=row["difficulty"],
            exam_track=row["exam_track"],
            reason=row["reason"] or "",
            requested_by=row["requested_by"] or "user",
            status=ScopeRequestStatus(row["status"]) if row["status"] else ScopeRequestStatus.PENDING,
            target_count=row["target_count"] or 5,
            fulfilled_count=row["fulfilled_count"] or 0,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            fulfilled_at=datetime.fromisoformat(row["fulfilled_at"]) if row["fulfilled_at"] else None,
            admin_notes=row["admin_notes"],
        )


# 單例
_repository: SQLiteScopeRequestRepository | None = None


def get_scope_request_repository() -> SQLiteScopeRequestRepository:
    """取得出題需求儲存庫實例（單例）"""
    global _repository
    if _repository is None:
        _repository = SQLiteScopeRequestRepository()
    return _repository
