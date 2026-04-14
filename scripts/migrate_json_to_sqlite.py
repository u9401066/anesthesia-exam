"""
資料遷移腳本: JSON → SQLite

將 data/questions/*.json 遷移到 SQLite 資料庫。
此腳本會：
1. 讀取所有 JSON 題目檔案
2. 儲存到 SQLite 資料庫
3. 記錄遷移日誌（audit log）
4. 可選擇性備份並刪除原始 JSON 檔案

使用方式:
    uv run python scripts/migrate_json_to_sqlite.py
    uv run python scripts/migrate_json_to_sqlite.py --delete-json  # 遷移後刪除 JSON
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 添加專案路徑
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.entities.question import Difficulty, Question, QuestionType, Source
from src.domain.value_objects.audit import ActorType
from src.infrastructure.persistence.sqlite_question_repo import SQLiteQuestionRepository


def migrate_json_to_sqlite(delete_json: bool = False):
    """執行遷移"""

    questions_dir = PROJECT_ROOT / "data" / "questions"
    backup_dir = PROJECT_ROOT / "data" / "questions_backup"

    if not questions_dir.exists():
        print("❌ data/questions 目錄不存在")
        return

    json_files = list(questions_dir.glob("*.json"))

    if not json_files:
        print("ℹ️ 沒有 JSON 檔案需要遷移")
        return

    print(f"📋 找到 {len(json_files)} 個 JSON 檔案")
    print()

    # 建立 Repository
    repo = SQLiteQuestionRepository()

    # 遷移統計
    migrated = 0
    skipped = 0
    failed = 0

    for filepath in json_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            question_id = data.get("id", "")

            # 檢查是否已存在
            existing = repo.get_by_id(question_id)
            if existing:
                print(f"⏭️ 跳過 (已存在): {question_id}")
                skipped += 1
                continue

            # 建立來源
            source = None
            source_data = data.get("source")
            if source_data and isinstance(source_data, dict):
                source = Source(
                    document=source_data.get("document", ""),
                    page=source_data.get("page"),
                    lines=source_data.get("lines"),
                    original_text=source_data.get("original_text"),
                )

            # 處理難度
            difficulty_str = data.get("difficulty", "medium")
            try:
                difficulty = Difficulty(difficulty_str)
            except ValueError:
                difficulty = Difficulty.MEDIUM

            # 處理題型
            q_type_str = data.get("question_type", "single_choice")
            try:
                question_type = QuestionType(q_type_str)
            except ValueError:
                question_type = QuestionType.SINGLE_CHOICE

            # 處理時間
            created_at_str = data.get("created_at")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                except ValueError:
                    created_at = datetime.now()
            else:
                created_at = datetime.now()

            # 建立 Question 實體
            question = Question(
                id=question_id,
                question_text=data.get("question_text", data.get("question", "")),
                options=data.get("options", []),
                correct_answer=data.get("correct_answer", data.get("answer", "")),
                explanation=data.get("explanation", ""),
                source=source,
                question_type=question_type,
                difficulty=difficulty,
                topics=data.get("topics", []),
                points=data.get("points", 1),
                image_path=data.get("image_path"),
                created_at=created_at,
                created_by=data.get("created_by", "agent"),
            )

            # 儲存到 SQLite
            generation_context = {
                "migrated_from": filepath.name,
                "migration_date": datetime.now().isoformat(),
                "original_data": data,
            }

            repo.save(
                question=question,
                actor_type=ActorType.SYSTEM,
                actor_name="migrate_json_to_sqlite",
                generation_context=generation_context,
            )

            print(f"✅ 遷移成功: {question_id}")
            migrated += 1

        except Exception as e:
            print(f"❌ 遷移失敗 {filepath.name}: {e}")
            failed += 1

    print()
    print("=" * 50)
    print("📊 遷移結果:")
    print(f"   ✅ 成功: {migrated}")
    print(f"   ⏭️ 跳過: {skipped}")
    print(f"   ❌ 失敗: {failed}")

    # 刪除或備份 JSON 檔案
    if delete_json and migrated > 0:
        print()
        print("🗑️ 備份並刪除 JSON 檔案...")

        backup_dir.mkdir(parents=True, exist_ok=True)

        for filepath in json_files:
            try:
                # 備份
                shutil.copy2(filepath, backup_dir / filepath.name)
                # 刪除
                filepath.unlink()
                print(f"   刪除: {filepath.name}")
            except Exception as e:
                print(f"   ❌ 刪除失敗 {filepath.name}: {e}")

        print(f"✅ 備份位置: {backup_dir}")


def main():
    """主函數"""
    import argparse

    parser = argparse.ArgumentParser(description="將 JSON 題目遷移到 SQLite 資料庫")
    parser.add_argument("--delete-json", action="store_true", help="遷移後刪除原始 JSON 檔案（會先備份）")

    args = parser.parse_args()

    print("=" * 50)
    print("📦 JSON → SQLite 資料遷移")
    print("=" * 50)
    print()

    migrate_json_to_sqlite(delete_json=args.delete_json)


if __name__ == "__main__":
    main()
