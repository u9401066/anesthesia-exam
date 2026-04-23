"""
Database Connection - SQLite 資料庫連線管理

提供 SQLite 資料庫的連線和初始化功能。
"""

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Generator

from src.infrastructure.logging import get_logger
from sqlalchemy.pool import QueuePool

# 預設資料庫路徑
DB_PATH_ENV_VAR = "ANESTHESIA_EXAM_DB_PATH"
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "questions.db"
SQLITE_POOL_SIZE_ENV_VAR = "ANESTHESIA_EXAM_SQLITE_POOL_SIZE"
SQLITE_MAX_OVERFLOW_ENV_VAR = "ANESTHESIA_EXAM_SQLITE_MAX_OVERFLOW"
SQLITE_POOL_TIMEOUT_ENV_VAR = "ANESTHESIA_EXAM_SQLITE_POOL_TIMEOUT"
SQLITE_BUSY_TIMEOUT_MS_ENV_VAR = "ANESTHESIA_EXAM_SQLITE_BUSY_TIMEOUT_MS"
SQLITE_WAL_AUTOCHECKPOINT_ENV_VAR = "ANESTHESIA_EXAM_SQLITE_WAL_AUTOCHECKPOINT"
SQLITE_ENABLE_WAL_ENV_VAR = "ANESTHESIA_EXAM_SQLITE_ENABLE_WAL"
DEFAULT_SQLITE_POOL_SIZE = 8
DEFAULT_SQLITE_MAX_OVERFLOW = 16
DEFAULT_SQLITE_POOL_TIMEOUT = 30.0
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 15000
DEFAULT_SQLITE_WAL_AUTOCHECKPOINT = 1000
logger = get_logger(__name__)
_POOL_REGISTRY: dict[str, QueuePool] = {}
_POOL_SIGNATURES: dict[str, tuple[int, int, float, int, int, bool]] = {}
_POOL_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class SQLiteRuntimeConfig:
    """Resolved per-process runtime config for pooled SQLite connections."""

    pool_size: int
    max_overflow: int
    pool_timeout: float
    busy_timeout_ms: int
    wal_autocheckpoint: int
    enable_wal: bool

    def signature(self) -> tuple[int, int, float, int, int, bool]:
        return (
            self.pool_size,
            self.max_overflow,
            self.pool_timeout,
            self.busy_timeout_ms,
            self.wal_autocheckpoint,
            self.enable_wal,
        )


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(int(value), minimum)
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(float(value), minimum)
    except ValueError:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_sqlite_runtime_config() -> SQLiteRuntimeConfig:
    """Resolve SQLite pool and hardening settings from the environment."""
    return SQLiteRuntimeConfig(
        pool_size=_env_int(SQLITE_POOL_SIZE_ENV_VAR, DEFAULT_SQLITE_POOL_SIZE),
        max_overflow=_env_int(SQLITE_MAX_OVERFLOW_ENV_VAR, DEFAULT_SQLITE_MAX_OVERFLOW, minimum=0),
        pool_timeout=_env_float(SQLITE_POOL_TIMEOUT_ENV_VAR, DEFAULT_SQLITE_POOL_TIMEOUT),
        busy_timeout_ms=_env_int(SQLITE_BUSY_TIMEOUT_MS_ENV_VAR, DEFAULT_SQLITE_BUSY_TIMEOUT_MS),
        wal_autocheckpoint=_env_int(
            SQLITE_WAL_AUTOCHECKPOINT_ENV_VAR,
            DEFAULT_SQLITE_WAL_AUTOCHECKPOINT,
        ),
        enable_wal=_env_flag(SQLITE_ENABLE_WAL_ENV_VAR, True),
    )


def _pool_key(db_path: Path) -> str:
    return str(db_path.resolve())


def _apply_sqlite_pragmas(conn, db_path: Path, config: SQLiteRuntimeConfig) -> str:
    cursor = conn.cursor()
    journal_mode = "delete"

    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute(f"PRAGMA busy_timeout = {config.busy_timeout_ms}")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA temp_store = MEMORY")
    cursor.execute(f"PRAGMA wal_autocheckpoint = {config.wal_autocheckpoint}")

    if config.enable_wal:
        try:
            cursor.execute("PRAGMA journal_mode = WAL")
            row = cursor.fetchone()
            if row:
                journal_mode = str(row[0]).lower()
        except sqlite3.OperationalError as exc:
            logger.warning("sqlite_wal_enable_failed", db_path=str(db_path), error=str(exc))
            cursor.execute("PRAGMA journal_mode")
            row = cursor.fetchone()
            if row:
                journal_mode = str(row[0]).lower()
    else:
        cursor.execute("PRAGMA journal_mode")
        row = cursor.fetchone()
        if row:
            journal_mode = str(row[0]).lower()

    return journal_mode


def _open_sqlite_connection(db_path: Path, config: SQLiteRuntimeConfig):
    conn = sqlite3.connect(
        db_path,
        timeout=config.busy_timeout_ms / 1000,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    journal_mode = _apply_sqlite_pragmas(conn, db_path, config)
    logger.debug(
        "sqlite_connection_configured",
        db_path=str(db_path),
        busy_timeout_ms=config.busy_timeout_ms,
        journal_mode=journal_mode,
    )
    return conn


def dispose_connection_pool(db_path: Path | None = None) -> None:
    """Dispose a pooled connection set so future checkouts get fresh connections."""
    db_path = db_path or get_db_path()
    key = _pool_key(db_path)
    with _POOL_LOCK:
        pool = _POOL_REGISTRY.pop(key, None)
        _POOL_SIGNATURES.pop(key, None)
    if pool is not None:
        pool.dispose()
        logger.info("sqlite_pool_disposed", db_path=str(db_path))


def get_connection_pool(db_path: Path | None = None) -> QueuePool:
    """Return a per-process SQLAlchemy QueuePool for SQLite connections."""
    db_path = (db_path or get_db_path()).resolve()
    config = resolve_sqlite_runtime_config()
    key = _pool_key(db_path)
    signature = config.signature()

    with _POOL_LOCK:
        existing = _POOL_REGISTRY.get(key)
        if existing is not None and _POOL_SIGNATURES.get(key) != signature:
            existing.dispose()
            _POOL_REGISTRY.pop(key, None)
            _POOL_SIGNATURES.pop(key, None)
            logger.info("sqlite_pool_recreated_for_new_config", db_path=str(db_path))

        pool = _POOL_REGISTRY.get(key)
        if pool is None:
            pool = QueuePool(
                creator=lambda path=db_path, runtime_config=config: _open_sqlite_connection(path, runtime_config),
                pool_size=config.pool_size,
                max_overflow=config.max_overflow,
                timeout=config.pool_timeout,
                reset_on_return="rollback",
                use_lifo=True,
            )
            _POOL_REGISTRY[key] = pool
            _POOL_SIGNATURES[key] = signature
            logger.info(
                "sqlite_pool_created",
                db_path=str(db_path),
                pool_size=config.pool_size,
                max_overflow=config.max_overflow,
                pool_timeout=config.pool_timeout,
                busy_timeout_ms=config.busy_timeout_ms,
                enable_wal=config.enable_wal,
            )

    return pool


def _checkout_pooled_connection(pool: QueuePool, db_path: Path):
    conn = pool.connect()
    try:
        conn.execute("SELECT 1")
    except Exception as exc:
        logger.warning("sqlite_pool_ping_failed", db_path=str(db_path), error=str(exc))
        try:
            conn.invalidate(exc)
        except Exception:
            conn.close()
        conn = pool.connect()
        conn.execute("SELECT 1")
    return conn


def begin_immediate_transaction(conn) -> None:
    """Upgrade write transactions to BEGIN IMMEDIATE when not already in one."""
    if not getattr(conn, "in_transaction", False):
        conn.execute("BEGIN IMMEDIATE")


def get_db_path() -> Path:
    """取得資料庫路徑"""
    override = os.getenv(DB_PATH_ENV_VAR)
    return Path(override) if override else DEFAULT_DB_PATH


def init_database(db_path: Path | None = None) -> None:
    """
    初始化資料庫 Schema

    Args:
        db_path: 資料庫路徑，None 則使用預設路徑
    """
    db_path = db_path or get_db_path()
    config = resolve_sqlite_runtime_config()
    log = logger.bind(db_path=str(db_path))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log.debug("database_init_start")

    try:
        with _open_sqlite_connection(db_path, config) as conn:
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
        _init_past_exam_tables(db_path, config)

        # ─── Schema Migration ───
        _run_migrations(db_path, config)

        # ─── Scope Request Schema ───
        _init_scope_request_tables(db_path, config)

        # ─── Draft Question Schema ───
        _init_question_draft_tables(db_path, config)
    except Exception as exc:
        log.exception("database_init_failed", error=str(exc))
        raise
    dispose_connection_pool(db_path)
    log.debug("database_init_complete")


def _init_past_exam_tables(db_path: Path, config: SQLiteRuntimeConfig) -> None:
    """初始化考古題相關表"""
    with _open_sqlite_connection(db_path, config) as conn:
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


def _run_migrations(db_path: Path, config: SQLiteRuntimeConfig) -> None:
    """執行 Schema 增量遷移（冪等）"""
    applied_migrations: list[str] = []
    with _open_sqlite_connection(db_path, config) as conn:
        cursor = conn.cursor()

        # Migration: 新增 exam_track 欄位 (v2026.04)
        cursor.execute("PRAGMA table_info(questions)")
        columns = {row[1] for row in cursor.fetchall()}

        if "exam_track" not in columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN exam_track TEXT")
            applied_migrations.append("add_questions_exam_track")

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

    if applied_migrations:
        logger.info("database_migrations_applied", db_path=str(db_path), migrations=applied_migrations)


def _init_scope_request_tables(db_path: Path, config: SQLiteRuntimeConfig) -> None:
    """初始化出題需求 (Scope Request) 表"""
    with _open_sqlite_connection(db_path, config) as conn:
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


def _init_question_draft_tables(db_path: Path, config: SQLiteRuntimeConfig) -> None:
    """初始化題目草稿箱表。"""
    with _open_sqlite_connection(db_path, config) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS question_drafts (
                id TEXT PRIMARY KEY,
                question_data TEXT NOT NULL,
                source_confidence TEXT DEFAULT 'none',
                status TEXT DEFAULT 'draft',
                is_starred INTEGER DEFAULT 0,
                notes TEXT,
                origin TEXT DEFAULT 'generated_review',
                template_data TEXT,
                blueprint_data TEXT,
                qa_metadata TEXT,
                promoted_question_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        cursor.execute("PRAGMA table_info(question_drafts)")
        draft_columns = {row[1] for row in cursor.fetchall()}

        if "template_data" not in draft_columns:
            cursor.execute("ALTER TABLE question_drafts ADD COLUMN template_data TEXT")
        if "blueprint_data" not in draft_columns:
            cursor.execute("ALTER TABLE question_drafts ADD COLUMN blueprint_data TEXT")
        if "qa_metadata" not in draft_columns:
            cursor.execute("ALTER TABLE question_drafts ADD COLUMN qa_metadata TEXT")

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_question_drafts_status
            ON question_drafts (status)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_question_drafts_starred
            ON question_drafts (is_starred)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_question_drafts_updated_at
            ON question_drafts (updated_at)
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS question_draft_versions (
                id TEXT PRIMARY KEY,
                draft_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                reason TEXT,
                snapshot_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (draft_id) REFERENCES question_drafts (id)
            )
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_question_draft_versions_unique
            ON question_draft_versions (draft_id, version_number)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_question_draft_versions_draft_id
            ON question_draft_versions (draft_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_question_draft_versions_created_at
            ON question_draft_versions (created_at)
            """
        )

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
    db_path = db_path or get_db_path()
    log = logger.bind(db_path=str(db_path))

    # 確保資料庫已初始化
    if not db_path.exists():
        log.info("database_file_missing_initializing")
        init_database(db_path)

    pool = get_connection_pool(db_path)
    conn = _checkout_pooled_connection(pool, db_path)
    log.debug(
        "db_connection_checkout",
        pool_status=pool.status(),
    )

    try:
        yield conn
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        log.exception("db_connection_error", error=str(exc))
        raise
    finally:
        conn.close()
        log.debug(
            "db_connection_checkin",
            pool_status=pool.status(),
        )
