"""Audit Miller chapter figure assets and emit a reusable JSON quality report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_MCP_ROOT = PROJECT_ROOT / "libs" / "asset-aware-mcp"
DEFAULT_CHAPTER_DIR = PROJECT_ROOT / "Miller anesthesia章節分割版"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "reports" / "image_audit"

VERY_LOW_VARIANCE_THRESHOLD = 5.0
LOW_VARIANCE_THRESHOLD = 15.0
TINY_AREA_THRESHOLD = 20_000
SMALL_AREA_THRESHOLD = 80_000


@dataclass
class FigureRecord:
    doc_id: str
    title: str
    page: int
    caption: str
    path: str
    width: int
    height: int
    area: int
    variance: float | None
    path_status: str
    old_root_prefix: bool
    relative_prefix: bool
    recoverable: bool
    missing: bool
    unreadable: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit figure quality for split Miller chapter ingest outputs."
    )
    parser.add_argument("--chapter-dir", type=Path, default=DEFAULT_CHAPTER_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--match", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-chapter", type=int, default=0)
    parser.add_argument("--end-chapter", type=int, default=0)
    return parser.parse_args()


def configure_asset_mcp_path() -> None:
    if str(ASSET_MCP_ROOT) not in sys.path:
        sys.path.insert(0, str(ASSET_MCP_ROOT))


def sort_key(path: Path) -> tuple[int, str]:
    prefix = path.name.split(" - ", 1)[0].strip()
    if prefix.isdigit():
        return (int(prefix), path.name)
    return (10**9, path.name)


def chapter_number_from_path(path: Path) -> int:
    prefix = path.name.split(" - ", 1)[0].strip()
    return int(prefix) if prefix.isdigit() else 0


def find_chapter_pdfs(
    chapter_dir: Path,
    match: str,
    limit: int,
    start_chapter: int,
    end_chapter: int,
) -> list[Path]:
    pdfs = [
        path
        for path in sorted(chapter_dir.glob("*.pdf"), key=sort_key)
        if not path.name.startswith("._")
    ]
    if start_chapter > 0 or end_chapter > 0:
        filtered: list[Path] = []
        for path in pdfs:
            chapter_number = chapter_number_from_path(path)
            if chapter_number == 0:
                continue
            if start_chapter > 0 and chapter_number < start_chapter:
                continue
            if end_chapter > 0 and chapter_number > end_chapter:
                continue
            filtered.append(path)
        pdfs = filtered
    if match:
        pdfs = [path for path in pdfs if match in path.name]
    if limit > 0:
        pdfs = pdfs[:limit]
    return pdfs


def build_doc_id_for_pdf(pdf_path: Path) -> str:
    configure_asset_mcp_path()
    from src.application.document_service import build_doc_id_unique_suffix
    from src.domain.value_objects import DocId

    return DocId.generate(
        pdf_path.stem,
        build_doc_id_unique_suffix(pdf_path),
    ).value


def measure_variance(image_path: Path) -> tuple[int, int, float]:
    with Image.open(image_path) as image:
        grayscale = image.convert("L")
        stat = ImageStat.Stat(grayscale)
        variance = float(stat.var[0]) if stat.var else 0.0
        width, height = grayscale.size
    return width, height, variance


def resolve_figure_path(
    raw_path: str,
    *,
    data_dir: Path,
    basename_index: dict[str, list[Path]],
) -> tuple[Path | None, str, bool]:
    if not raw_path:
        return None, "missing", False

    candidate = Path(raw_path)
    if candidate.exists():
        return candidate, "ok", False

    if not candidate.is_absolute():
        repo_relative = (PROJECT_ROOT / candidate).resolve()
        if repo_relative.exists():
            return repo_relative, "ok", False

    basename_matches = basename_index.get(candidate.name, [])
    if len(basename_matches) == 1:
        return basename_matches[0], "recoverable", True

    return None, "missing", False


def safe_caption(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def build_basename_index(data_dir: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for image_path in data_dir.glob("doc_*/images/*"):
        if image_path.is_file():
            index[image_path.name].append(image_path)
    return index


def collect_records(
    chapter_pdfs: list[Path],
    *,
    data_dir: Path,
) -> list[FigureRecord]:
    basename_index = build_basename_index(data_dir)
    records: list[FigureRecord] = []

    for pdf_path in chapter_pdfs:
        doc_id = build_doc_id_for_pdf(pdf_path)
        manifest_path = data_dir / doc_id / f"{doc_id}_manifest.json"
        if not manifest_path.exists():
            continue

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        title = str(manifest.get("title") or pdf_path.stem)
        assets = manifest.get("assets") if isinstance(manifest, dict) else {}
        figures = assets.get("figures") if isinstance(assets, dict) else []
        if not isinstance(figures, list):
            continue

        for figure in figures:
            if not isinstance(figure, dict):
                continue

            raw_path = str(figure.get("path") or "")
            resolved_path, path_status, recoverable = resolve_figure_path(
                raw_path,
                data_dir=data_dir,
                basename_index=basename_index,
            )
            unreadable = False
            variance: float | None = None
            width = int(figure.get("width") or 0)
            height = int(figure.get("height") or 0)

            if resolved_path is not None:
                try:
                    width, height, variance = measure_variance(resolved_path)
                except Exception:
                    unreadable = True
                    path_status = "unreadable"

            records.append(
                FigureRecord(
                    doc_id=doc_id,
                    title=title,
                    page=int(figure.get("page") or 0),
                    caption=safe_caption(figure.get("caption")),
                    path=raw_path,
                    width=width,
                    height=height,
                    area=width * height,
                    variance=variance,
                    path_status=path_status,
                    old_root_prefix=raw_path.startswith("/root/"),
                    relative_prefix=raw_path.startswith("../../") or raw_path.startswith("../"),
                    recoverable=recoverable,
                    missing=path_status == "missing",
                    unreadable=unreadable,
                )
            )

    return records


def chapter_summary(records: list[FigureRecord]) -> list[dict[str, Any]]:
    grouped: dict[str, list[FigureRecord]] = defaultdict(list)
    for record in records:
        grouped[record.doc_id].append(record)

    rows: list[dict[str, Any]] = []
    for doc_id, items in grouped.items():
        total = len(items)
        no_caption_count = sum(1 for item in items if not item.caption)
        tiny_count = sum(1 for item in items if item.area < TINY_AREA_THRESHOLD)
        low_variance_count = sum(
            1
            for item in items
            if item.variance is not None and item.variance < LOW_VARIANCE_THRESHOLD
        )
        rows.append(
            {
                "doc_id": doc_id,
                "title": items[0].title,
                "figure_count": total,
                "no_caption_count": no_caption_count,
                "no_caption_ratio": round(no_caption_count / total, 4) if total else 0.0,
                "tiny_count": tiny_count,
                "tiny_ratio": round(tiny_count / total, 4) if total else 0.0,
                "low_variance_count": low_variance_count,
                "low_variance_ratio": round(low_variance_count / total, 4) if total else 0.0,
            }
        )
    return sorted(rows, key=lambda row: (-int(row["figure_count"]), str(row["title"])))


def page_summary(records: list[FigureRecord]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[FigureRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.doc_id, record.page)].append(record)

    rows: list[dict[str, Any]] = []
    for (doc_id, page), items in grouped.items():
        total = len(items)
        no_caption_count = sum(1 for item in items if not item.caption)
        tiny_count = sum(1 for item in items if item.area < TINY_AREA_THRESHOLD)
        low_variance_count = sum(
            1
            for item in items
            if item.variance is not None and item.variance < LOW_VARIANCE_THRESHOLD
        )
        captioned_count = total - no_caption_count
        rows.append(
            {
                "doc_id": doc_id,
                "title": items[0].title,
                "page": page,
                "figure_count": total,
                "captioned_count": captioned_count,
                "no_caption_count": no_caption_count,
                "tiny_count": tiny_count,
                "low_variance_count": low_variance_count,
            }
        )
    return sorted(
        rows,
        key=lambda row: (-int(row["figure_count"]), str(row["title"]), int(row["page"])),
    )


def build_report(
    records: list[FigureRecord],
    *,
    chapter_dir: Path,
    data_dir: Path,
) -> dict[str, Any]:
    path_counter = Counter(record.path_status for record in records)
    current_prefix = sum(
        1 for record in records if record.path.startswith(str(data_dir.resolve()))
    )
    path_stats = {
        "unreadable": path_counter["unreadable"],
        "missing": path_counter["missing"],
        "recoverable": sum(1 for record in records if record.recoverable),
        "old_root_prefix": sum(1 for record in records if record.old_root_prefix),
        "ok": path_counter["ok"],
        "current_prefix": current_prefix,
        "relative_prefix": sum(1 for record in records if record.relative_prefix),
    }

    content_stats = {
        "total": len(records),
        "tiny_lt_20k_area": sum(1 for record in records if record.area < TINY_AREA_THRESHOLD),
        "lt_80k_area": sum(1 for record in records if record.area < SMALL_AREA_THRESHOLD),
        "low_variance": sum(
            1
            for record in records
            if record.variance is not None and record.variance < LOW_VARIANCE_THRESHOLD
        ),
        "very_low_variance": sum(
            1
            for record in records
            if record.variance is not None and record.variance < VERY_LOW_VARIANCE_THRESHOLD
        ),
    }

    chapters = chapter_summary(records)
    pages = page_summary(records)
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "chapter_dir": str(chapter_dir),
        "data_dir": str(data_dir),
        "global": {
            "path_stats": path_stats,
            "content_stats": content_stats,
        },
        "top_figure_heavy_chapters": chapters[:20],
        "top_figure_heavy_pages": pages[:20],
    }


def main() -> int:
    args = parse_args()
    chapter_dir = args.chapter_dir.resolve()
    data_dir = args.data_dir.resolve()
    report_dir = args.report_dir.resolve()

    chapter_pdfs = find_chapter_pdfs(
        chapter_dir,
        args.match,
        args.limit,
        args.start_chapter,
        args.end_chapter,
    )
    records = collect_records(chapter_pdfs, data_dir=data_dir)
    report = build_report(records, chapter_dir=chapter_dir, data_dir=data_dir)

    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"summary_{timestamp}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    latest_path = report_dir / "summary.json"
    latest_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"records={len(records)}")
    print(f"report={report_path}")
    print(f"latest={latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
