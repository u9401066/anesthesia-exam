from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.past_exam_figure_service import PastExamFigureService


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02"
    b"\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_BYTES)


def _write_manifest(doc_dir: Path, doc_id: str, figures: list[dict]) -> None:
    manifest = {
        "doc_id": doc_id,
        "title": doc_id,
        "assets": {
            "figures": figures,
        },
    }
    (doc_dir / f"{doc_id}_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_resolve_question_assets_maps_placeholder_options_to_same_page_figures(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    doc_id = "doc_fixture_exam"
    doc_dir = data_dir / doc_id
    images_dir = doc_dir / "images"

    figures = []
    for suffix in [1, 2, 3, 4, 5, 800]:
        image_name = f"fig_28_{suffix}.png"
        _write_png(images_dir / image_name)
        figures.append(
            {
                "id": f"fig_28_{suffix}",
                "page": 28,
                "path": f"/root/workspace260209/anesthesia-exam/data/{doc_id}/images/{image_name}",
                "ext": "png",
                "caption": "",
            }
        )

    _write_manifest(doc_dir, doc_id, figures)
    preview_path = data_dir / "past_exam_page_cache" / doc_id / "page_28.png"
    _write_png(preview_path)

    service = PastExamFigureService(data_dir=data_dir)
    monkeypatch.setattr(service, "_render_pdf_page_preview", lambda doc, page: preview_path)

    enriched = service.enrich_question(
        {
            "pattern": "image_based",
            "source_doc_id": doc_id,
            "source_page": 28,
            "options": ["圖像選項 A", "圖像選項 B", "圖像選項 C", "圖像選項 D", "圖像選項 E"],
        }
    )

    assert enriched["image_asset_status"] == "resolved"
    assert enriched["source_page_image_path"] == str(preview_path)
    assert [asset["label"] for asset in enriched["option_figure_assets"]] == ["A", "B", "C", "D", "E"]
    assert [Path(asset["path"]).name for asset in enriched["option_figure_assets"]] == [
        "fig_28_1.png",
        "fig_28_2.png",
        "fig_28_3.png",
        "fig_28_4.png",
        "fig_28_5.png",
    ]
    assert enriched["figure_assets"] == []


def test_resolve_question_assets_keeps_same_page_figures_for_non_placeholder_image_question(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    doc_id = "doc_fixture_non_placeholder"
    doc_dir = data_dir / doc_id
    images_dir = doc_dir / "images"

    figures = []
    for suffix in [1, 2]:
        image_name = f"fig_29_{suffix}.png"
        _write_png(images_dir / image_name)
        figures.append(
            {
                "id": f"fig_29_{suffix}",
                "page": 29,
                "path": str(images_dir / image_name),
                "ext": "png",
                "caption": f"Figure {suffix}",
            }
        )

    _write_manifest(doc_dir, doc_id, figures)
    service = PastExamFigureService(data_dir=data_dir)
    monkeypatch.setattr(service, "_render_pdf_page_preview", lambda doc, page: None)

    enriched = service.enrich_question(
        {
            "pattern": "image_based",
            "source_doc_id": doc_id,
            "source_page": 29,
            "options": ["這是文字選項 A", "這是文字選項 B", "這是文字選項 C", "這是文字選項 D"],
        }
    )

    assert enriched["image_asset_status"] == "resolved"
    assert enriched["option_figure_assets"] == []
    assert [asset["id"] for asset in enriched["figure_assets"]] == ["fig_29_1", "fig_29_2"]


def test_resolve_question_assets_marks_hist_questions_without_doc_assets_for_reingest(tmp_path: Path) -> None:
    service = PastExamFigureService(data_dir=tmp_path / "data")

    enriched = service.enrich_question(
        {
            "pattern": "image_based",
            "source_doc_id": "hist_114_written",
            "source_page": 1,
            "options": ["A", "B", "C", "D"],
        }
    )

    assert enriched["image_asset_status"] == "needs_reingest"
    assert "需要重新建立帶圖資的來源映射" in enriched["image_asset_note"]