import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.entities.question import Question  # noqa: E402
from src.infrastructure.persistence.database import (  # noqa: E402
    dispose_connection_pool,
    get_connection,
    get_connection_pool,
    init_database,
)
from src.infrastructure.persistence.sqlite_question_repo import SQLiteQuestionRepository  # noqa: E402


def test_sqlite_connection_pool_applies_hardening_pragmas(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "pooled-hardening.db"
    monkeypatch.setenv("ANESTHESIA_EXAM_DB_PATH", str(db_path))
    monkeypatch.setenv("ANESTHESIA_EXAM_SQLITE_POOL_SIZE", "3")
    monkeypatch.setenv("ANESTHESIA_EXAM_SQLITE_MAX_OVERFLOW", "1")

    dispose_connection_pool(db_path)
    init_database(db_path)

    pool_a = get_connection_pool(db_path)
    pool_b = get_connection_pool(db_path)

    assert pool_a is pool_b
    assert pool_a.size() == 3

    with get_connection(db_path) as conn:
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 15000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1

    dispose_connection_pool(db_path)


def test_sqlite_connection_pool_handles_concurrent_question_writes(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "pooled-concurrency.db"
    monkeypatch.setenv("ANESTHESIA_EXAM_DB_PATH", str(db_path))
    monkeypatch.setenv("ANESTHESIA_EXAM_SQLITE_POOL_SIZE", "4")
    monkeypatch.setenv("ANESTHESIA_EXAM_SQLITE_MAX_OVERFLOW", "4")

    dispose_connection_pool(db_path)
    repo = SQLiteQuestionRepository(db_path=db_path)

    def save_question(index: int) -> str:
        question = Question(
            question_text=f"Concurrent pooled question {index}",
            options=["A", "B", "C", "D"],
            correct_answer="A",
            explanation="pool smoke",
            topics=["pool-smoke"],
            created_by="pytest-pool",
        )
        return repo.save(question=question, actor_name="pytest-pool")

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(save_question, range(18)))

    assert len(results) == 18
    assert repo.get_statistics()["total"] == 18

    dispose_connection_pool(db_path)