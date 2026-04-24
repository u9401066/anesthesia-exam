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


def test_assess_document_source_readiness_reuses_cached_block_stats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_doc(
        tmp_path,
        doc_id="doc_cached",
        title="Miller Cached Chapter",
        markdown="# Cached Chapter\n\nShock therapy overview.",
        blocks=[
            {
                "block_id": "blk_0001",
                "block_type": "Text",
                "page": 4,
                "text": "Shock therapy overview.",
                "bbox": [],
                "section_hierarchy": {"1": "Cached Chapter"},
                "metadata": {"line_start": 1, "line_end": 1},
            }
        ],
    )

    original_read_text = Path.read_text
    read_count = 0

    def counted_read_text(path: Path, *args, **kwargs):
        nonlocal read_count
        if path.name == "blocks.json":
            read_count += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)

    service = TextbookGenerationService(tmp_path)
    first = service.assess_document_source_readiness("doc_cached")
    second = service.assess_document_source_readiness("doc_cached")

    assert first == second
    assert read_count == 1


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


def test_question_formal_save_ready_rejects_image_based_questions_even_with_complete_evidence(tmp_path: Path) -> None:
    service = TextbookGenerationService(tmp_path)

    assert (
        service.question_formal_save_ready(
            {
                "pattern": "image_based",
                "source": {
                    "document": "Miller Chapter 79",
                    "stem_source": {"page": 1, "line_start": 10, "line_end": 10, "original_text": "figure stem"},
                    "answer_source": {
                        "page": 1,
                        "line_start": 11,
                        "line_end": 11,
                        "original_text": "figure answer",
                    },
                    "explanation_sources": [
                        {
                            "page": 1,
                            "line_start": 12,
                            "line_end": 12,
                            "original_text": "figure explanation",
                        }
                    ],
                },
                "formal_save_ready": True,
            }
        )
        is False
    )


def test_build_evidence_pack_prefers_source_ready_pack_over_higher_score_incomplete_pack(
    tmp_path: Path, monkeypatch
) -> None:
    _write_doc(
        tmp_path,
        doc_id="doc_complete",
        title="Complete Source Doc",
        markdown="# Complete\n\nBody.",
        blocks=[
            {
                "block_id": "complete_blk",
                "block_type": "Text",
                "page": 2,
                "text": "complete support",
                "bbox": [1, 2, 3, 4],
                "section_hierarchy": {"1": "Complete Chapter", "2": "Complete Section"},
                "metadata": {"line_start": 2, "line_end": 2},
            }
        ],
    )
    _write_doc(
        tmp_path,
        doc_id="doc_incomplete",
        title="Incomplete Source Doc",
        markdown="# Incomplete\n\nBody.",
        blocks=[
            {
                "block_id": "incomplete_blk",
                "block_type": "Text",
                "page": 3,
                "text": "incomplete support",
                "bbox": [1, 2, 3, 4],
                "section_hierarchy": {"1": "Incomplete Chapter", "2": "Incomplete Section"},
                "metadata": {"line_start": 4, "line_end": 4},
            }
        ],
    )

    service = TextbookGenerationService(tmp_path)

    monkeypatch.setattr(service, "_stem_queries", lambda _question: ["stem"])
    monkeypatch.setattr(service, "_answer_queries", lambda _question: ["answer"])
    monkeypatch.setattr(service, "_explanation_queries", lambda _question: ["explanation"])

    def fake_find_best_match(blocks, queries, _preferred_sections):
        block_id = blocks[0]["block_id"]
        if block_id == "complete_blk":
            if queries == ["stem"]:
                return {**blocks[0], "score": 0.6}
            if queries == ["answer"]:
                return {**blocks[0], "score": 0.6}
            return None

        if queries == ["stem"]:
            return {**blocks[0], "score": 2.5}
        if queries == ["answer"]:
            return None
        return None

    monkeypatch.setattr(service, "_find_best_match", fake_find_best_match)
    monkeypatch.setattr(service, "_find_explanation_matches", lambda _blocks, _queries, _sections: [])

    pack = service._build_evidence_pack(
        question={
            "question_text": "unused",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
            "explanation": "unused",
            "topics": [],
        },
        selected_doc_ids=["doc_complete", "doc_incomplete"],
        selected_sections=[{"doc_id": "doc_complete", "title": "Complete Section"}],
        readiness_by_doc={
            "doc_complete": {"source_ready": True, "gate_reasons": []},
            "doc_incomplete": {"source_ready": True, "gate_reasons": []},
        },
        prompt_context={"selected_section_titles": ["Complete Section"]},
    )

    assert pack["source_ready"] is True
    assert pack["matched_doc_id"] == "doc_complete"
    assert pack["source"]["answer_source"]["page"] == 2


def test_enrich_generated_questions_prefers_source_ready_doc_with_section_hints_in_multi_doc_mode(
    tmp_path: Path,
) -> None:
    _write_doc(
        tmp_path,
        doc_id="doc_complete_realistic",
        title="Complete Source Doc",
        markdown="""# Pediatric Critical Care

## Therapy and Outcomes

Primary management in shock starts with correcting the underlying cause.
Early resuscitation targets restoring microvascular oxygen delivery across multiple regional tissue beds.

## Post-Resuscitation Care

Ongoing reassessment is required after initial stabilization.
""",
        blocks=[
            {
                "block_id": "complete_stem",
                "block_type": "Text",
                "page": 10,
                "text": "Primary management in shock starts with correcting the underlying cause.",
                "bbox": [1, 2, 3, 4],
                "section_hierarchy": {"1": "Pediatric Critical Care", "2": "Therapy and Outcomes"},
                "metadata": {"line_start": 4, "line_end": 4},
            },
            {
                "block_id": "complete_answer",
                "block_type": "Text",
                "page": 11,
                "text": "Early resuscitation targets restoring microvascular oxygen delivery across multiple regional tissue beds.",
                "bbox": [2, 3, 4, 5],
                "section_hierarchy": {"1": "Pediatric Critical Care", "2": "Therapy and Outcomes"},
                "metadata": {"line_start": 5, "line_end": 5},
            },
        ],
    )
    _write_doc(
        tmp_path,
        doc_id="doc_incomplete_realistic",
        title="Incomplete Source Doc",
        markdown="""# Shock Overview

## Background

What is the primary goal of shock treatment?
""",
        blocks=[
            {
                "block_id": "incomplete_stem",
                "block_type": "Text",
                "page": 20,
                "text": "What is the primary goal of shock treatment?",
                "bbox": [1, 2, 3, 4],
                "section_hierarchy": {"1": "Shock Overview", "2": "Background"},
                "metadata": {"line_start": 3, "line_end": 3},
            }
        ],
    )

    service = TextbookGenerationService(tmp_path)
    questions = service.enrich_generated_questions(
        [
            {
                "question_text": "What is the primary goal of shock treatment?",
                "options": [
                    "Restoring microvascular oxygen delivery across multiple regional tissue beds during early hemodynamic resuscitation",
                    "Delaying perfusion support until vasopressors fail",
                    "Reducing urine output to conserve intravascular volume",
                    "Avoiding reassessment after initial stabilization",
                ],
                "correct_answer": "A",
                "explanation": "The therapeutic priority is correcting the underlying cause while restoring microvascular oxygen delivery across multiple regional tissue beds during early hemodynamic resuscitation.",
                "difficulty": "medium",
                "topics": ["Shock", "Resuscitation"],
            }
        ],
        selected_doc_ids=["doc_complete_realistic", "doc_incomplete_realistic"],
        selected_sections=[
            {"doc_id": "doc_complete_realistic", "title": "Therapy and Outcomes"},
            {"doc_id": "doc_complete_realistic", "title": "Post-Resuscitation Care"},
        ],
        preview_only=False,
    )

    question = questions[0]
    assert question["formal_save_ready"] is True
    assert question["evidence_pack"]["matched_doc_id"] == "doc_complete_realistic"
    assert question["source"]["document"] == "Complete Source Doc"
    assert question["source"]["section"] == "Therapy and Outcomes"
    assert question["source"]["stem_source"]["page"] == 10
    assert question["source"]["answer_source"]["page"] == 11
    assert len(question["source"]["explanation_sources"]) >= 1
