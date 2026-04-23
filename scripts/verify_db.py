"""快速驗證 SQLite"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infrastructure.logging import bootstrap_logging, get_logger, new_run_id
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

logger = get_logger(__name__)


def main() -> None:
    run_id = new_run_id("verifydb")
    bootstrap_logging(__name__, extra_context={"run_id": run_id, "provider": "verify-db"})

    repo = get_question_repository()
    stats = repo.get_statistics()
    questions = repo.list_all(limit=3)
    logger.info("verify_db_completed", total=stats["total"], validated=stats["validated"], preview_count=len(questions))

    print("=== SQLite 題庫統計 ===")
    print(f"總題數: {stats['total']}")
    print(f"難度分布: {stats['by_difficulty']}")
    print(f"已驗證: {stats['validated']}")
    print()
    print("=== 最近 3 題 ===")
    for q in questions:
        print(f"- [{q.id}] {q.question_text[:40]}...")


if __name__ == "__main__":
    main()
