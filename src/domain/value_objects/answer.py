"""Shared helpers for answer formatting and question-type normalization."""

from __future__ import annotations

import re
from typing import Any


_QUESTION_TYPE_ALIASES: dict[str, str] = {
    "single": "single_choice",
    "single_choice": "single_choice",
    "single-choice": "single_choice",
    "singlechoice": "single_choice",
    "sc": "single_choice",
    "mcq": "single_choice",
    "s": "single_choice",
    "single題": "single_choice",
    "單選": "single_choice",
    "單選題": "single_choice",

    "multiple": "multiple_choice",
    "multiple_choice": "multiple_choice",
    "multiple-choice": "multiple_choice",
    "multiplechoice": "multiple_choice",
    "mcq_multi": "multiple_choice",
    "多選": "multiple_choice",
    "多選題": "multiple_choice",

    "true_false": "true_false",
    "true-false": "true_false",
    "truefalse": "true_false",
    "tf": "true_false",
    "t/f": "true_false",
    "是非": "true_false",
    "是非題": "true_false",
    "非選": "true_false",

    "fill_in_blank": "fill_in_blank",
    "fill-in-blank": "fill_in_blank",
    "fillblank": "fill_in_blank",
    "填充": "fill_in_blank",
    "填空": "fill_in_blank",
    "填空題": "fill_in_blank",

    "short_answer": "short_answer",
    "short-answer": "short_answer",
    "shortanswer": "short_answer",
    "簡答": "short_answer",
    "簡答題": "short_answer",

    "essay": "essay",
    "問答": "essay",
    "問答題": "essay",

    "image_based": "image_based",
    "image-based": "image_based",
    "imagebased": "image_based",
    "影像": "image_based",
    "圖像題": "image_based",
    "圖片題": "image_based",
}


def normalize_answer_letters(raw_answer: Any, option_count: int | None = None) -> tuple[str, ...]:
    """Normalize answer string/list to a sorted tuple of uppercase A-Z letters."""
    if raw_answer is None:
        return tuple()

    if isinstance(raw_answer, (list, tuple, set)):
        raw_items = list(raw_answer)
    else:
        raw_items = [raw_answer]

    max_index = option_count - 1 if option_count and option_count > 0 else None
    letters: set[str] = set()

    for item in raw_items:
        normalized = str(item or "").upper().replace("，", ",").replace("；", ",")
        for match in re.findall(r"[A-Za-z]", normalized):
            char = match.upper()
            if not ("A" <= char <= "Z"):
                continue
            index = ord(char) - ord("A")
            if max_index is not None and index > max_index:
                continue
            letters.add(char)

    return tuple(sorted(letters))


def format_answer_letters(raw_answer: Any, option_count: int | None = None) -> str:
    """Format answer letters into stable comma separated output."""
    return ",".join(normalize_answer_letters(raw_answer, option_count=option_count))


def coerce_question_type(raw_type: Any, fallback_pattern: Any | None = None) -> str:
    """Coerce free-form question_type / pattern values to QuestionType values."""
    if isinstance(raw_type, str):
        normalized = raw_type.strip().lower().replace(" ", "_").replace("\u3000", "_")
        normalized = re.sub(r"[^a-z0-9_/-]", "", normalized)
        normalized = normalized.strip("_-")
        if normalized in _QUESTION_TYPE_ALIASES:
            return _QUESTION_TYPE_ALIASES[normalized]

    if isinstance(fallback_pattern, str):
        normalized_pattern = fallback_pattern.strip().lower().replace(" ", "_")
        if normalized_pattern in {
            "image_based",
            "image-based",
            "imagebased",
            "direct_recall",
            "clinical_scenario",
            "comparison",
            "mechanism",
            "calculation",
            "best_answer",
            "negation",
            "sequence",
        }:
            if "image" in normalized_pattern:
                return "image_based"
            return "single_choice"

    if isinstance(raw_type, str):
        if raw_type.strip().lower() in {"single", "singlechoice", "single_choice", "single-choice", "mcq"}:
            return "single_choice"
        if raw_type.strip().lower() in {"multiple", "multiplechoice", "multiple_choice", "multiple-choice", "多選", "多選題"}:
            return "multiple_choice"
        if raw_type.strip().lower() in {"tf", "t/f", "true_false", "true-false", "truefalse", "是非", "是非題"}:
            return "true_false"
        if raw_type.strip().lower() in {"fill_in_blank", "fill-in-blank", "fillblank", "填空", "填空題"}:
            return "fill_in_blank"
        if raw_type.strip().lower() in {"short_answer", "short-answer", "shortanswer", "簡答", "簡答題"}:
            return "short_answer"
        if raw_type.strip().lower() in {"essay", "問答", "問答題"}:
            return "essay"
        if raw_type.strip().lower() in {"image_based", "image-based", "imagebased", "影像題", "圖片題", "圖像題"}:
            return "image_based"

    return "single_choice"


def question_allows_multiple(
    question: dict[str, Any] | str,
    option_count: int | None = None,
    correct_answer: Any | None = None,
) -> bool:
    """Infer whether question should allow multiple-choice answers."""
    if isinstance(question, str):
        question_type = question
        answer_source = correct_answer
        question_payload = {}
    elif isinstance(question, dict):
        question_type = (
            question.get("question_type")
            or question.get("question_type_normalized")
            or question.get("pattern")
            or question.get("question_type_hint")
            or ""
        )
        answer_source = correct_answer if correct_answer is not None else question.get("correct_answer")
        question_payload = question
    else:
        question_type = ""
        answer_source = correct_answer
        question_payload = {}

    canonical_type = coerce_question_type(question_type, fallback_pattern=question_payload.get("pattern") if isinstance(question_payload, dict) else None)

    if canonical_type == "multiple_choice":
        return True
    if canonical_type in {"true_false", "fill_in_blank", "short_answer", "essay", "image_based"}:
        return False

    normalized_correct = normalize_answer_letters(answer_source, option_count=option_count)
    return len(normalized_correct) > 1
