#!/usr/bin/env python3
"""Batch-generate past-exam explanations and write them into the formal DB."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.past_exam_explanation_service import (  # noqa: E402
    PastExamExplanationService,
    _truncate_text,
)
from src.infrastructure.logging import bootstrap_logging, new_run_id  # noqa: E402
from src.infrastructure.persistence.sqlite_past_exam_repo import SQLitePastExamRepository  # noqa: E402
from src.infrastructure.persistence.sqlite_question_repo import SQLiteQuestionRepository  # noqa: E402


logger = bootstrap_logging(
    __name__,
    extra_context={"run_id": new_run_id("batch-explain"), "provider": "script"},
)

LETTER_LABELS = ["A", "B", "C", "D", "E", "F"]
LATIN_STOPWORDS = {
    "about",
    "after",
    "among",
    "because",
    "between",
    "choice",
    "correct",
    "during",
    "following",
    "from",
    "goal",
    "incorrect",
    "option",
    "patient",
    "question",
    "regarding",
    "therapy",
    "these",
    "this",
    "those",
    "under",
    "which",
    "with",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "questions.db")
    parser.add_argument("--year", type=int, required=True, help="Target exam year, e.g. 2025 for 114-year exam.")
    parser.add_argument("--limit", type=int, default=10, help="Max questions to fill in this batch.")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many missing-explanation rows first.")
    parser.add_argument("--dry-run", action="store_true", help="Generate but do not write back.")
    parser.add_argument(
        "--pdf-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "2020 Miller's Anesthesia 9th.pdf",
        help="PDF used for lightweight textbook retrieval.",
    )
    parser.add_argument(
        "--text-cache-path",
        type=Path,
        default=PROJECT_ROOT / ".cache" / "miller_2020.txt",
        help="Cached plain-text extraction used for retrieval.",
    )
    parser.add_argument(
        "--opencode-config",
        type=Path,
        default=PROJECT_ROOT / "opencode.json",
        help="OpenCode config used to resolve the fallback LLM endpoint.",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=280,
        help="Reject generated explanations shorter than this many characters.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Retry generation when the output is too short or misses option-by-option coverage.",
    )
    return parser.parse_args()


def ensure_backup(db_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}.backup.{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    logger.info("past_exam_db_backup_created", db_path=str(db_path), backup_path=str(backup_path))
    return backup_path


def ensure_pdf_text_cache(pdf_path: Path, text_cache_path: Path) -> Path:
    text_cache_path.parent.mkdir(parents=True, exist_ok=True)
    if text_cache_path.exists() and text_cache_path.stat().st_size > 0:
        return text_cache_path

    subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), str(text_cache_path)],
        check=True,
        cwd=str(PROJECT_ROOT),
    )
    logger.info("past_exam_pdf_text_cache_created", pdf_path=str(pdf_path), text_cache_path=str(text_cache_path))
    return text_cache_path


def load_target_questions(repo: SQLitePastExamRepository, year: int, *, offset: int, limit: int) -> list[dict]:
    questions = [
        question.to_dict()
        for question in repo.list_all_questions(limit=None, explanation_required=False)
        if question.exam_year == year and not str(question.explanation or "").strip()
    ]
    questions.sort(key=lambda question: int(question.get("question_number") or 0))
    return questions[offset : offset + limit]


def tokenize_question(question: dict) -> list[str]:
    candidates: list[str] = []
    candidates.extend(question.get("concept_names", []) or [])
    candidates.extend(question.get("topics", []) or [])

    question_text = str(question.get("question_text") or "")
    candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9.+/-]{3,}", question_text))
    candidates.extend(re.findall(r"[\u4e00-\u9fff]{2,}", question_text))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        token = str(candidate or "").strip()
        if not token:
            continue
        normalized = token.lower()
        if normalized in LATIN_STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(token)
    return deduped[:8]


def build_miller_snippets(text_lines: list[str], question: dict, *, limit: int = 3) -> list[str]:
    query_terms = tokenize_question(question)
    if not query_terms:
        return []

    snippets: list[tuple[float, str]] = []
    question_tokens = {token.lower() for token in query_terms}

    for index, line in enumerate(text_lines):
        normalized_line = line.lower()
        matched_terms = [term for term in query_terms if term.lower() in normalized_line]
        if not matched_terms:
            continue

        window = text_lines[max(0, index - 2) : min(len(text_lines), index + 3)]
        snippet = "\n".join(part.rstrip() for part in window if part.strip())
        if not snippet.strip():
            continue

        latin_tokens = set(re.findall(r"[a-z0-9.+/-]{3,}", snippet.lower()))
        score = len(matched_terms) * 2.0 + len(question_tokens & latin_tokens) * 0.25
        snippets.append((score, snippet))

    deduped: list[str] = []
    seen: set[str] = set()
    for _score, snippet in sorted(snippets, key=lambda item: item[0], reverse=True):
        compact = re.sub(r"\s+", " ", snippet).strip()
        if compact in seen:
            continue
        seen.add(compact)
        deduped.append(_truncate_text(snippet, 900))
        if len(deduped) >= limit:
            break
    return deduped


def build_prompt(
    service: PastExamExplanationService,
    question: dict,
    references: list[dict],
    miller_snippets: list[str],
) -> str:
    base_prompt = service.build_generation_prompt(question, references)
    option_lines = []
    for index, option in enumerate(question.get("options", [])):
        label = LETTER_LABELS[index] if index < len(LETTER_LABELS) else f"Opt{index + 1}"
        option_lines.append(f"{label}. {option}")

    sections = [
        base_prompt,
        "",
        "額外要求：",
        "- 詳解必須以考生可直接閱讀的繁體中文撰寫。",
        "- 請逐一標出 A/B/C/D（若有 E 也要包含）並解釋每個選項為何對或錯。",
        "- 請用麻醉學與重症醫學的標準知識寫作，若教材片段不足以直接涵蓋全題，請維持保守且教學導向。",
        "- 不要捏造頁碼、章節號或不存在的書上原文。",
        "",
        "本題選項：",
        "\n".join(option_lines),
    ]

    if miller_snippets:
        sections.extend(
            [
                "",
                "Miller 檢索片段（僅作知識校正與脈絡參考）：",
            ]
        )
        for index, snippet in enumerate(miller_snippets, start=1):
            sections.append(f"[Miller 片段 {index}]\n{snippet}")

    sections.extend(
        [
            "",
            '請只輸出單一 JSON 物件，例如 {"explanation":"..."}。',
        ]
    )
    return "\n".join(sections)


def validate_explanation(question: dict, explanation: str, min_length: int) -> tuple[bool, str]:
    cleaned = explanation.strip()
    if len(cleaned) < min_length:
        return False, f"詳解過短（{len(cleaned)} < {min_length}）"

    required_labels = LETTER_LABELS[: len(question.get("options", []))]
    missing_labels = [label for label in required_labels if label not in cleaned]
    if missing_labels:
        return False, f"詳解未逐一涵蓋選項：{', '.join(missing_labels)}"

    return True, "ok"


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")
    if not args.pdf_path.exists():
        raise SystemExit(f"PDF not found: {args.pdf_path}")

    backup_path = ensure_backup(args.db)
    text_cache_path = ensure_pdf_text_cache(args.pdf_path, args.text_cache_path)
    text_lines = text_cache_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    past_exam_repo = SQLitePastExamRepository(db_path=args.db)
    question_repo = SQLiteQuestionRepository(db_path=args.db)
    service = PastExamExplanationService(
        past_exam_repo=past_exam_repo,
        question_repo=question_repo,
        opencode_config_path=args.opencode_config,
        request_timeout=120,
    )

    targets = load_target_questions(
        past_exam_repo,
        args.year,
        offset=args.offset,
        limit=args.limit,
    )
    if not targets:
        print("No target questions found.")
        print(f"Backup kept at: {backup_path}")
        return 0

    generated_count = 0
    errors: list[dict[str, str]] = []

    for index, question in enumerate(targets, start=1):
        question_id = str(question.get("id") or "")
        references = service.find_reference_matches(question, limit=5)
        miller_snippets = build_miller_snippets(text_lines, question, limit=3)
        prompt = build_prompt(service, question, references, miller_snippets)

        logger.info(
            "past_exam_batch_generation_start",
            batch_index=index,
            question_id=question_id,
            exam_year=question.get("exam_year"),
            question_number=question.get("question_number"),
            reference_count=len(references),
            miller_snippet_count=len(miller_snippets),
        )

        try:
            explanation = ""
            raw_response = ""
            failure_reason = ""
            for attempt in range(1, args.max_attempts + 1):
                attempt_prompt = prompt
                if failure_reason:
                    attempt_prompt += (
                        "\n\n前一版輸出未通過檢查："
                        + failure_reason
                        + "\n請重新輸出更完整版本，務必逐一說明 A/B/C/D/E 選項，且內容至少數百字。"
                    )
                raw_response = service._invoke_llm(attempt_prompt, provider=None)  # noqa: SLF001
                explanation = service._extract_explanation(raw_response)  # noqa: SLF001
                valid, reason = validate_explanation(question, explanation, args.min_length)
                if valid:
                    break
                failure_reason = reason
                logger.warning(
                    "past_exam_batch_generation_retry",
                    question_id=question_id,
                    attempt=attempt,
                    reason=reason,
                )
            else:
                raise ValueError(failure_reason or "generation validation failed")

            if not args.dry_run:
                saved = past_exam_repo.update_question_explanation(question_id, explanation)
                if not saved:
                    raise RuntimeError("DB update returned False")

            generated_count += 1
            print(
                json.dumps(
                    {
                        "question_id": question_id,
                        "question_number": question.get("question_number"),
                        "saved": not args.dry_run,
                        "reference_count": len(references),
                        "miller_snippet_count": len(miller_snippets),
                        "explanation_len": len(explanation),
                    },
                    ensure_ascii=False,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "past_exam_batch_generation_failed",
                question_id=question_id,
                error=str(exc),
            )
            errors.append(
                {
                    "question_id": question_id,
                    "question_number": str(question.get("question_number") or ""),
                    "error": str(exc),
                }
            )

    summary = {
        "year": args.year,
        "requested_limit": args.limit,
        "generated_count": generated_count,
        "error_count": len(errors),
        "dry_run": args.dry_run,
        "backup_path": str(backup_path),
        "text_cache_path": str(text_cache_path),
        "error_examples": errors[:5],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
