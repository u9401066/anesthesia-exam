#!/usr/bin/env python3
"""Repair the 109/2020 written-exam answer key in the formal SQLite DB."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_written_past_exams import ASSET_DOC_IDS, VERIFIED_109_ANSWER_TEXT, parse_answer_pairs  # noqa: E402
from src.infrastructure.logging import bootstrap_logging, new_run_id  # noqa: E402
from src.infrastructure.persistence.database import begin_immediate_transaction, get_connection  # noqa: E402


logger = bootstrap_logging(
    __name__,
    extra_context={"run_id": new_run_id("repair109"), "provider": "script"},
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "questions.db")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the diff without writing.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow updating even if the current answers are not all BONUS.",
    )
    return parser.parse_args()


def build_verified_answer_map() -> dict[int, str]:
    answer_map = parse_answer_pairs(VERIFIED_109_ANSWER_TEXT)
    expected_numbers = set(range(1, 101))
    if set(answer_map) != expected_numbers:
        missing = sorted(expected_numbers - set(answer_map))
        extra = sorted(set(answer_map) - expected_numbers)
        raise ValueError(
            f"verified 109 answer map malformed: missing={missing[:5]} extra={extra[:5]}"
        )
    invalid_answers = {
        number: answer for number, answer in answer_map.items() if answer not in {"A", "B", "C", "D", "E"}
    }
    if invalid_answers:
        raise ValueError(f"verified 109 answer map contains invalid answers: {invalid_answers}")
    return answer_map


def create_backup(db_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}.backup.{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    logger.info("repair_109_backup_created", db_path=str(db_path), backup_path=str(backup_path))
    return backup_path


def load_target_rows(db_path: Path) -> list[dict[str, object]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, exam_year, source_doc_id, question_number, correct_answer
            FROM past_exam_questions
            WHERE exam_year = 2020
              AND source_doc_id = ?
            ORDER BY question_number ASC
            """,
            (ASSET_DOC_IDS[109],),
        )
        return [dict(row) for row in cursor.fetchall()]


def summarize_answers(rows: list[dict[str, object]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row["correct_answer"] or "") for row in rows).items()))


def sample_diff(
    rows: list[dict[str, object]],
    verified_map: dict[int, str],
    *,
    limit: int = 8,
) -> list[dict[str, object]]:
    changed: list[dict[str, object]] = []
    for row in rows:
        question_number = int(row["question_number"])
        before = str(row["correct_answer"] or "")
        after = verified_map[question_number]
        if before == after:
            continue
        changed.append(
            {
                "question_number": question_number,
                "before": before,
                "after": after,
            }
        )
    return changed[:limit]


def apply_updates(db_path: Path, verified_map: dict[int, str]) -> int:
    with get_connection(db_path) as conn:
        begin_immediate_transaction(conn)
        cursor = conn.cursor()
        updated_count = 0
        for question_number, answer in sorted(verified_map.items()):
            cursor.execute(
                """
                UPDATE past_exam_questions
                SET correct_answer = ?
                WHERE exam_year = 2020
                  AND source_doc_id = ?
                  AND question_number = ?
                """,
                (answer, ASSET_DOC_IDS[109], question_number),
            )
            updated_count += cursor.rowcount
        conn.commit()
    logger.info("repair_109_answers_applied", updated_count=updated_count)
    return updated_count


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")

    verified_map = build_verified_answer_map()
    before_rows = load_target_rows(args.db)
    if len(before_rows) != 100:
        raise SystemExit(f"Expected 100 target rows for 109/2020, found {len(before_rows)}")

    question_numbers = [int(row["question_number"]) for row in before_rows]
    if question_numbers != list(range(1, 101)):
        raise SystemExit("Target rows do not cover question numbers 1..100 in order")

    before_summary = summarize_answers(before_rows)
    if before_summary != {"BONUS": 100} and not args.force:
        raise SystemExit(
            "Refusing to update because current answers are not all BONUS. "
            "Re-run with --force if you intentionally want to overwrite them."
        )

    preview = sample_diff(before_rows, verified_map)
    backup_path = None if args.dry_run else create_backup(args.db)
    updated_count = 0 if args.dry_run else apply_updates(args.db, verified_map)
    after_rows = load_target_rows(args.db)
    after_summary = summarize_answers(after_rows)

    report = {
        "db_path": str(args.db),
        "dry_run": args.dry_run,
        "target_exam_year": 2020,
        "target_source_doc_id": ASSET_DOC_IDS[109],
        "row_count": len(before_rows),
        "backup_path": str(backup_path) if backup_path else None,
        "updated_count": updated_count,
        "before_answer_summary": before_summary,
        "after_answer_summary": after_summary,
        "changed_samples": preview,
        "post_check": {
            "all_answers_are_single_choice": all(
                str(row["correct_answer"] or "") in {"A", "B", "C", "D", "E"} for row in after_rows
            ),
            "bonus_rows_remaining": sum(1 for row in after_rows if str(row["correct_answer"] or "") == "BONUS"),
            "first_five_answers": [
                {
                    "question_number": int(row["question_number"]),
                    "correct_answer": str(row["correct_answer"] or ""),
                }
                for row in after_rows[:5]
            ],
            "last_five_answers": [
                {
                    "question_number": int(row["question_number"]),
                    "correct_answer": str(row["correct_answer"] or ""),
                }
                for row in after_rows[-5:]
            ],
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
