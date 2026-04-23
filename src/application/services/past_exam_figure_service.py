"""Resolve image assets for imported past-exam questions."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from src.infrastructure.logging import get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
PLACEHOLDER_OPTION_RE = re.compile(r"^\s*圖像選項\s+([A-E])\s*$")
FIGURE_ID_RE = re.compile(r"fig_(\d+)_(\d+)$")
logger = get_logger(__name__)


class PastExamFigureService:
    """Attach page-level figure assets and page previews to image-based past-exam questions."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self._manifest_cache: dict[str, dict | None] = {}

    def enrich_question(self, question: dict) -> dict:
        """Return a question dict annotated with figure assets when available."""
        enriched = dict(question)
        asset_payload = self.resolve_question_assets(question)
        if asset_payload:
            enriched.update(asset_payload)
        return enriched

    def resolve_question_assets(self, question: dict) -> dict:
        """Resolve option figures / page figures / page preview for a past-exam question."""
        if not self._should_resolve_assets(question):
            return {}

        doc_id = str(question.get("source_doc_id") or "").strip()
        source_page = int(question.get("source_page") or 0)
        options = list(question.get("options", []) or [])

        default_payload = {
            "option_figure_assets": [],
            "figure_assets": [],
            "source_page_image_path": None,
            "image_asset_status": "missing",
            "image_asset_note": None,
        }
        if not doc_id or source_page <= 0:
            default_payload["image_asset_note"] = "此題屬於圖片題，但目前缺少可定位的來源文件或頁碼。"
            return default_payload

        figures = self._load_page_figures(doc_id, source_page)
        option_labels = self._placeholder_option_labels(options)
        option_figure_assets = self._match_option_figures(figures, option_labels)
        source_page_image_path = self._render_pdf_page_preview(doc_id, source_page)

        if option_figure_assets or figures or source_page_image_path:
            return {
                "option_figure_assets": option_figure_assets,
                "figure_assets": [] if option_figure_assets else figures,
                "source_page_image_path": str(source_page_image_path) if source_page_image_path else None,
                "image_asset_status": "resolved",
                "image_asset_note": None,
            }

        default_payload["image_asset_status"] = "needs_reingest"
        default_payload["image_asset_note"] = (
            f"這題被判定為圖片題，但目前 {doc_id} 沒有可回接的圖資；"
            "106-108 / 114 這類舊匯入資料通常需要重新建立帶圖資的來源映射。"
        )
        return default_payload

    def _should_resolve_assets(self, question: dict) -> bool:
        pattern = str(question.get("pattern") or "").strip().lower()
        options = list(question.get("options", []) or [])
        if pattern == "image_based":
            return True
        return bool(self._placeholder_option_labels(options))

    def _load_page_figures(self, doc_id: str, source_page: int) -> list[dict]:
        manifest = self._load_manifest(doc_id)
        if manifest is None:
            return []

        doc_dir = self.data_dir / doc_id
        raw_figures = (((manifest.get("assets") or {}).get("figures")) or [])
        figures: list[dict] = []
        for raw_figure in raw_figures:
            if int(raw_figure.get("page") or 0) != source_page:
                continue

            resolved_path = self._resolve_figure_path(doc_dir, raw_figure)
            if resolved_path is None:
                continue

            figure_id = str(raw_figure.get("id") or resolved_path.stem)
            figures.append(
                {
                    "id": figure_id,
                    "page": source_page,
                    "path": str(resolved_path),
                    "caption": str(raw_figure.get("caption") or "").strip(),
                    "path_name": resolved_path.name,
                    "local_index": self._figure_local_index(figure_id, resolved_path.stem),
                }
            )

        return sorted(figures, key=lambda item: (item["local_index"], item["path_name"]))

    def _load_manifest(self, doc_id: str) -> dict | None:
        if doc_id in self._manifest_cache:
            return self._manifest_cache[doc_id]

        doc_dir = self.data_dir / doc_id
        manifest_paths = [doc_dir / f"{doc_id}_manifest.json", doc_dir / "manifest.json"]
        for manifest_path in manifest_paths:
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self._manifest_cache[doc_id] = manifest
                return manifest

        self._manifest_cache[doc_id] = None
        return None

    def _resolve_figure_path(self, doc_dir: Path, raw_figure: dict) -> Path | None:
        raw_path = str(raw_figure.get("path") or "").strip()
        if raw_path:
            normalized = self._normalize_workspace_path(raw_path)
            if normalized.exists():
                return normalized

            basename = Path(raw_path).name
            for folder_name in ("images", "figures"):
                candidate = doc_dir / folder_name / basename
                if candidate.exists():
                    return candidate

        figure_id = str(raw_figure.get("id") or "").strip()
        ext = str(raw_figure.get("ext") or "png").strip().lstrip(".") or "png"
        for folder_name in ("images", "figures"):
            candidate = doc_dir / folder_name / f"{figure_id}.{ext}"
            if candidate.exists():
                return candidate
        return None

    def _normalize_workspace_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            return candidate

        try:
            if candidate.exists():
                return candidate
        except OSError:
            pass

        parts = candidate.parts
        if "anesthesia-exam" not in parts:
            return candidate

        project_index = parts.index("anesthesia-exam")
        return PROJECT_ROOT.joinpath(*parts[project_index + 1 :])

    def _match_option_figures(self, figures: list[dict], option_labels: list[str]) -> list[dict]:
        if not option_labels:
            return []

        primary_figures = [figure for figure in figures if figure["local_index"] < 100]
        selected_pool = primary_figures if len(primary_figures) >= len(option_labels) else figures
        if len(selected_pool) < len(option_labels):
            return []

        selected = []
        for label, figure in zip(option_labels, selected_pool[: len(option_labels)]):
            selected.append({**figure, "label": label})
        return selected

    def _placeholder_option_labels(self, options: list[str]) -> list[str]:
        labels: list[str] = []
        for option in options:
            match = PLACEHOLDER_OPTION_RE.fullmatch(str(option or "").strip())
            if match is None:
                return []
            labels.append(match.group(1).upper())
        return labels if len(labels) >= 4 else []

    def _figure_local_index(self, figure_id: str, fallback_stem: str) -> int:
        for candidate in (figure_id, fallback_stem):
            match = FIGURE_ID_RE.search(candidate)
            if match is not None:
                return int(match.group(2))
        return 10_000

    def _render_pdf_page_preview(self, doc_id: str, source_page: int) -> Path | None:
        source_pdf = self.data_dir / doc_id / "original.pdf"
        if not source_pdf.exists():
            return None

        cache_dir = self.data_dir / "past_exam_page_cache" / doc_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        preview_prefix = cache_dir / f"page_{source_page}"
        preview_path = preview_prefix.with_suffix(".png")
        if preview_path.exists():
            return preview_path

        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(source_page),
                    "-l",
                    str(source_page),
                    "-png",
                    "-singlefile",
                    str(source_pdf),
                    str(preview_prefix),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            logger.warning(
                "past_exam_page_preview_failed",
                doc_id=doc_id,
                source_page=source_page,
                error=str(exc),
            )
            return None

        return preview_path if preview_path.exists() else None


_service: PastExamFigureService | None = None


def get_past_exam_figure_service() -> PastExamFigureService:
    """Return the singleton service used by Streamlit past-exam views."""
    global _service
    if _service is None:
        _service = PastExamFigureService()
    return _service