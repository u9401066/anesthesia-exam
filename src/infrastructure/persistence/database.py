"""
Database Connection - SQLite 資料庫連線管理

提供 SQLite 資料庫的連線和初始化功能。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# 預設資料庫路徑
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "questions.db"


def get_db_path() -> Path:
    """取得資料庫路徑"""
    return DEFAULT_DB_PATH


def init_database(db_path: Path | None = None) -> None:
    """
    初始化資料庫 Schema

    Args:
        db_path: 資料庫路徑，None 則使用預設路徑
    """
    db_path = db_path or DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 題目主表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                question_text TEXT NOT NULL,
                options TEXT,           -- JSON array
                correct_answer TEXT NOT NULL,
                explanation TEXT,
                source TEXT,            -- JSON object
                question_type TEXT DEFAULT 'single_choice',
                difficulty TEXT DEFAULT 'medium',
                topics TEXT,            -- JSON array
                points INTEGER DEFAULT 1,
                image_path TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT DEFAULT 'agent',
                updated_at TEXT,
                is_deleted INTEGER DEFAULT 0,
                is_validated INTEGER DEFAULT 0,
                validation_notes TEXT
            )
        """)

        # 審計日誌表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_audits (
                id TEXT PRIMARY KEY,
                question_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                changes TEXT,           -- JSON object
                reason TEXT,
                generation_context TEXT, -- JSON object
                timestamp TEXT NOT NULL,
                FOREIGN KEY (question_id) REFERENCES questions (id)
            )
        """)

        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_questions_difficulty
            ON questions (difficulty)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_questions_type
            ON questions (question_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_questions_created_at
            ON questions (created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audits_question_id
            ON question_audits (question_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audits_timestamp
            ON question_audits (timestamp)
        """)

        # 全文搜尋表 (FTS5)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(
                id,
                question_text,
                options,
                explanation,
                topics,
                content='questions',
                content_rowid='rowid'
            )
        """)

        # 觸發器：同步 FTS
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS questions_ai AFTER INSERT ON questions BEGIN
                INSERT INTO questions_fts(rowid, id, question_text, options, explanation, topics)
                VALUES (new.rowid, new.id, new.question_text, new.options, new.explanation, new.topics);
            END
        """)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS questions_ad AFTER DELETE ON questions BEGIN
                INSERT INTO questions_fts(questions_fts, rowid, id, question_text, options, explanation, topics)
                VALUES('delete', old.rowid, old.id, old.question_text, old.options, old.explanation, old.topics);
            END
        """)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS questions_au AFTER UPDATE ON questions BEGIN
                INSERT INTO questions_fts(questions_fts, rowid, id, question_text, options, explanation, topics)
                VALUES('delete', old.rowid, old.id, old.question_text, old.options, old.explanation, old.topics);
                INSERT INTO questions_fts(rowid, id, question_text, options, explanation, topics)
                VALUES (new.rowid, new.id, new.question_text, new.options, new.explanation, new.topics);
            END
        """)

        conn.commit()

    # ─── 考古題 Schema ───
    _init_past_exam_tables(db_path)

    # ─── Schema Migration ───
    _run_migrations(db_path)

    # ─── Scope Request Schema ───
    _init_scope_request_tables(db_path)


def _init_past_exam_tables(db_path: Path) -> None:
    """初始化考古題相關表"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 考古題考卷表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS past_exams (
                id TEXT PRIMARY KEY,
                exam_year INTEGER NOT NULL,
                exam_name TEXT NOT NULL,
                total_questions INTEGER DEFAULT 0,
                source_pdf TEXT,
                source_doc_id TEXT,
                imported_at TEXT NOT NULL,
                imported_by TEXT DEFAULT 'agent',
                is_ocr_done INTEGER DEFAULT 0,
                is_parsed INTEGER DEFAULT 0,
                is_classified INTEGER DEFAULT 0
            )
        """)

        # 考古題題目表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS past_exam_questions (
                id TEXT PRIMARY KEY,
                past_exam_id TEXT NOT NULL,
                exam_year INTEGER NOT NULL,
                exam_name TEXT,
                question_number INTEGER DEFAULT 0,
                question_text TEXT NOT NULL,
                options TEXT,           -- JSON array
                correct_answer TEXT,
                explanation TEXT,
                concepts TEXT,          -- JSON array of concept IDs
                concept_names TEXT,     -- JSON array of concept names
                pattern TEXT DEFAULT 'direct_recall',
                difficulty TEXT DEFAULT 'medium',
                bloom_level INTEGER DEFAULT 1,
                topics TEXT,            -- JSON array
                source_doc_id TEXT,
                source_page INTEGER,
                raw_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (past_exam_id) REFERENCES past_exams (id)
            )
        """)

        # 概念表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                category TEXT,
                subcategory TEXT,
                keywords TEXT,          -- JSON array
                related_concepts TEXT    -- JSON array of concept IDs
            )
        """)

        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_past_exams_year
            ON past_exams (exam_year)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_peq_exam_id
            ON past_exam_questions (past_exam_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_peq_year
            ON past_exam_questions (exam_year)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_peq_pattern
            ON past_exam_questions (pattern)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_concepts_category
            ON concepts (category)
        """)

        # 考古題 FTS
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS past_exam_questions_fts USING fts5(
                id,
                question_text,
                options,
                explanation,
                concept_names,
                topics,
                content='past_exam_questions',
                content_rowid='rowid'
            )
        """)

        conn.commit()


def _run_migrations(db_path: Path) -> None:
    """執行 Schema 增量遷移（冪等）"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Migration: 新增 exam_track 欄位 (v2026.04)
        cursor.execute("PRAGMA table_info(questions)")
        columns = {row[1] for row in cursor.fetchall()}

        if "exam_track" not in columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN exam_track TEXT")

        if "exam_track" in columns or "exam_track" not in columns:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_questions_exam_track
                ON questions (exam_track)
            """)

        if "is_validated" in columns:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_questions_validated
                ON questions (is_validated)
            """)

        conn.commit()


def _init_scope_request_tables(db_path: Path) -> None:
    """初始化出題需求 (Scope Request) 表"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scope_requests (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                chapter TEXT,
                difficulty TEXT,
                exam_track TEXT,
                reason TEXT,
                requested_by TEXT DEFAULT 'user',
                status TEXT DEFAULT 'pending',
                target_count INTEGER DEFAULT 5,
                fulfilled_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                fulfilled_at TEXT,
                admin_notes TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scope_requests_status
            ON scope_requests (status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scope_requests_topic
            ON scope_requests (topic)
        """)

        conn.commit()


@contextmanager
def get_connection(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """
    取得資料庫連線（Context Manager）

    Args:
        db_path: 資料庫路徑

    Yields:
        SQLite 連線
    """
    db_path = db_path or DEFAULT_DB_PATH

    # 確保資料庫已初始化
    if not db_path.exists():
        init_database(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 支援以欄位名稱存取

    try:
        yield conn
    finally:
        conn.close()
