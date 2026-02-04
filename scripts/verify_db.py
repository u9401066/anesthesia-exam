"""快速驗證 SQLite"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

repo = get_question_repository()
stats = repo.get_statistics()
print("=== SQLite 題庫統計 ===")
print(f"總題數: {stats['total']}")
print(f"難度分布: {stats['by_difficulty']}")
print(f"已驗證: {stats['validated']}")
print()
print("=== 最近 3 題 ===")
questions = repo.list_all(limit=3)
for q in questions:
    print(f"- [{q.id}] {q.question_text[:40]}...")
