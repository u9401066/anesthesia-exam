"""
Database Connection - SQLite 資料庫連線管理

提供 SQLite 資料庫的連線和初始化功能。
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
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
