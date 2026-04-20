import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.textbook_generation_service import TextbookGenerationService  # noqa: E402


def _write_doc(tmp_path: Path, *, doc_id: str, title: str, markdown: str, blocks: list[dict]) -> Path:
    doc_dir = tmp_path / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        json.dumps({"doc_id": doc_id, "title": title, "assets": {"sections": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(markdown, encoding="utf-8")
    (doc_dir / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    return doc_dir


def test_assess_document_source_readiness_requires_searchable_blocks_and_lines(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        doc_id="doc_ready",
        title="Miller Chapter 79",
        markdown="# Chapter 79\n\nShock therapy overview.",
        blocks=[
            {
                "block_id": "blk_0001",
                "block_type": "Text",
                "page": 4,
                "text": "Shock therapy overview.",
                "bbox": [],
                "section_hierarchy": {"1": "Chapter 79"},
                "metadata": {"line_start": 1, "line_end": 1},
            }
        ],
    )

    readiness = TextbookGenerationService(tmp_path).assess_document_source_readiness("doc_ready")

    assert readiness["source_ready"] is True
    assert readiness["searchable_block_count"] == 1
    assert readiness["precise_block_count"] == 1


def test_build_prompt_context_prefers_selected_section_excerpt(tmp_path: Path) -> None:
    markdown = """# Pediatric and Neonatal Critical Care

Intro text.

## Therapy and Outcomes

The overall goal of therapy in shock is to treat the underlying cause.

## Family Centered Care

Families should be included in ICU decision making.
"""
    _write_doc(
        tmp_path,
        doc_id="doc_preview",
        title="Miller Chapter 79",
        markdown=markdown,
        blocks=[],
    )

    service = TextbookGenerationService(tmp_path)
    context = service.build_prompt_context(
        ["doc_preview"],
        [{"doc_id": "doc_preview", "title": "Therapy and Outcomes"}],
    )

    assert "Therapy and Outcomes" in context["prompt_context"]
    assert "underlying cause" in context["prompt_context"]
    assert "Family Centered Care" not in context["prompt_context"]


def test_enrich_generated_questions_marks_preview_only(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        doc_id="doc_preview_only",
        title="Miller Chapter 79",
        markdown="# Pediatric and Neonatal Critical Care\n\nKey text.",
        blocks=[],
    )
    service = TextbookGenerationService(tmp_path)

    questions = service.enrich_generated_questions(
        [
            {
                "question_text": "What is the goal of shock therapy?",
                "options": ["Restore oxygen delivery", "Increase sedation", "Delay antibiotics", "Ignore perfusion"],
                "correct_answer": "A",
                "explanation": "Shock therapy aims to restore oxygen delivery.",
                "difficulty": "medium",
                "topics": ["Shock"],
            }
        ],
        selected_doc_ids=["doc_preview_only"],
        selected_sections=[],
        preview_only=True,
    )

    assert questions[0]["preview_only"] is True
    assert questions[0]["formal_save_ready"] is False
    assert questions[0]["source"]["document"] == "Miller Chapter 79"
    assert "preview-only" in questions[0]["evidence_pack"]["gate_reasons"][0]


def test_enrich_generated_questions_builds_formal_evidence_pack(tmp_path: Path) -> None:
    markdown = """# Pediatric and Neonatal Critical Care

## Therapy and Outcomes

The overall goal of therapy in shock is to treat the underlying cause and return adequate oxygen delivery to the tissues.
Congenital heart disease causes significant alterations in oxygenation, perfusion, and myocardial function after birth.
"""
    _write_doc(
        tmp_path,
        doc_id="doc_formal",
        title="Miller Chapter 79",
        markdown=markdown,
        blocks=[
            {
                "block_id": "blk_0001",
                "block_type": "Text",
                "page": 6,
                "text": "The overall goal of therapy in shock is to treat the underlying cause and return adequate oxygen delivery to the tissues.",
                "bbox": [1, 2, 3, 4],
                "section_hierarchy": {"1": "Pediatric and Neonatal Critical Care", "2": "Therapy and Outcomes"},
                "metadata": {"line_start": 4, "line_end": 4},
            },
            {
                "block_id": "blk_0002",
                "block_type": "Text",
                "page": 4,
                "text": "Congenital heart disease causes significant alterations in oxygenation, perfusion, and myocardial function after birth.",
                "bbox": [2, 3, 4, 5],
                "section_hierarchy": {"1": "Pediatric and Neonatal Critical Care", "2": "Therapy and Outcomes"},
                "metadata": {"line_start": 5, "line_end": 5},
            },
        ],
    )

    service = TextbookGenerationService(tmp_path)
    questions = service.enrich_generated_questions(
        [
            {
                "question_text": "What is the overall goal of therapy in shock?",
                "options": [
                    "Treat the underlying cause and restore oxygen delivery",
                    "Delay perfusion support",
                    "Use family-centered rounds only",
                    "Avoid hemodynamic monitoring",
                ],
                "correct_answer": "A",
                "explanation": "The overall goal of therapy in shock is to treat the underlying cause and return adequate oxygen delivery to the tissues. Congenital heart disease also alters oxygenation and perfusion after birth.",
                "difficulty": "medium",
                "topics": ["Shock", "Perfusion"],
            }
        ],
        selected_doc_ids=["doc_formal"],
        selected_sections=[{"doc_id": "doc_formal", "title": "Therapy and Outcomes"}],
        preview_only=False,
    )

    question = questions[0]
    assert question["formal_save_ready"] is True
    assert question["preview_only"] is False
    assert question["source"]["document"] == "Miller Chapter 79"
    assert question["source"]["chapter"] == "Pediatric and Neonatal Critical Care"
    assert question["source"]["section"] == "Therapy and Outcomes"
    assert question["source"]["stem_source"]["page"] == 6
    assert question["source"]["answer_source"]["page"] == 6
    assert len(question["source"]["explanation_sources"]) >= 1
