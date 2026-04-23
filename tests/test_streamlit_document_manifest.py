from pathlib import Path

from src.presentation.streamlit.document_manifest import normalize_manifest_paths


def test_normalize_manifest_paths_rewrites_stale_project_absolute_paths(tmp_path: Path) -> None:
    project_dir = tmp_path / "anesthesia-exam"
    project_dir.mkdir()

    manifest = {
        "doc_id": "doc_109",
        "markdown_path": "/root/workspace260209/anesthesia-exam/data/doc_109/doc_109_full.md",
        "assets": {
            "figures": [
                {
                    "id": "fig_1",
                    "path": "/root/workspace260209/anesthesia-exam/data/doc_109/images/fig_1.png",
                    "caption": "/root/workspace260209/anesthesia-exam should remain descriptive text",
                }
            ]
        },
    }

    normalized = normalize_manifest_paths(manifest, project_dir=project_dir)

    assert normalized["markdown_path"] == str(project_dir / "data/doc_109/doc_109_full.md")
    assert normalized["assets"]["figures"][0]["path"] == str(project_dir / "data/doc_109/images/fig_1.png")
    assert normalized["assets"]["figures"][0]["caption"] == manifest["assets"]["figures"][0]["caption"]
