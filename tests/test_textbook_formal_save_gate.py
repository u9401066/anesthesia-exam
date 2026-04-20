import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.mcp import exam_server  # noqa: E402


def test_save_question_rejects_preview_only_textbook_payload(monkeypatch) -> None:
    saved = {"called": False}

    def fake_save(**_kwargs):
        saved["called"] = True
        return "question-1"

    monkeypatch.setattr(exam_server, "repo", type("Repo", (), {"save": staticmethod(fake_save)})())

    result = exam_server.save_question(
        {
            "question_text": "Shock goal?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
            "explanation": "Because.",
            "source_doc": "Miller Chapter 79",
            "preview_only": True,
        }
    )

    assert result["success"] is False
    assert "preview-only" in result["error"]
    assert saved["called"] is False


def test_save_question_requires_complete_textbook_evidence_pack(monkeypatch) -> None:
    saved = {"called": False}

    def fake_save(**_kwargs):
        saved["called"] = True
        return "question-1"

    monkeypatch.setattr(exam_server, "repo", type("Repo", (), {"save": staticmethod(fake_save)})())

    result = exam_server.save_question(
        {
            "question_text": "Shock goal?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
            "explanation": "Because.",
            "source_doc": "Miller Chapter 79",
            "stem_source": {"page": 1, "line_start": 10, "line_end": 10, "original_text": "shock line"},
            "answer_source": {"page": 1, "line_start": 11, "line_end": 11, "original_text": "answer line"},
        }
    )

    assert result["success"] is False
    assert "explanation_sources" in result["error"]
    assert saved["called"] is False


def test_save_question_accepts_complete_textbook_evidence_pack(monkeypatch) -> None:
    saved = {"called": False}

    def fake_save(**_kwargs):
        saved["called"] = True
        return "question-1"

    monkeypatch.setattr(exam_server, "repo", type("Repo", (), {"save": staticmethod(fake_save)})())

    result = exam_server.save_question(
        {
            "question_text": "Shock goal?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
            "explanation": "Because.",
            "source_doc": "Miller Chapter 79",
            "source_chapter": "Pediatric and Neonatal Critical Care",
            "source_section": "Therapy and Outcomes",
            "stem_source": {"page": 1, "line_start": 10, "line_end": 10, "original_text": "shock line"},
            "answer_source": {"page": 1, "line_start": 11, "line_end": 11, "original_text": "answer line"},
            "explanation_sources": [
                {"page": 1, "line_start": 10, "line_end": 11, "original_text": "supporting explanation line"}
            ],
        }
    )

    assert result["success"] is True
    assert saved["called"] is True
