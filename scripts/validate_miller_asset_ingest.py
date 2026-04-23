"""Validate Miller chapter ingest outputs and produce a reusable JSON report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_MCP_ROOT = PROJECT_ROOT / "libs" / "asset-aware-mcp"
DEFAULT_CHAPTER_DIR = PROJECT_ROOT / "Miller anesthesia章節分割版"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "reports"
PAGE_MARKER_RE = re.compile(r"<!--\s*Page\s+(\d+)\s*-->")


@dataclass
class ValidationEntry:
    chapter_number: int
    filename: str
    doc_id: str
    doc_dir_exists: bool
    manifest_exists: bool
    markdown_exists: bool
    blocks_exists: bool
    source_ready: bool
    searchable_block_count: int
    precise_block_count: int
    page_marker_count: int
    max_page_marker: int
    manifest_page_count: int
    figure_count: int
    table_count: int
    kg_entity_count: int
    errors: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate asset-aware ingest outputs for split Miller chapters."
    )
    parser.add_argument(
        "--chapter-dir",
        type=Path,
        default=DEFAULT_CHAPTER_DIR,
        help="Directory containing split Miller chapter PDFs.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Data directory containing per-document outputs.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory for JSON validation reports.",
    )
    parser.add_argument(
        "--match",
        default="",
        help="Only validate chapter files containing this substring.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of chapter PDFs to validate. 0 means all matched files.",
    )
    parser.add_argument(
        "--start-chapter",
        type=int,
        default=0,
        help="Inclusive starting chapter number filter. 0 means no lower bound.",
    )
    parser.add_argument(
        "--end-chapter",
        type=int,
        default=0,
        help="Inclusive ending chapter number filter. 0 means no upper bound.",
    )
    return parser.parse_args()


def configure_asset_mcp_path() -> None:
    if str(ASSET_MCP_ROOT) not in sys.path:
        sys.path.insert(0, str(ASSET_MCP_ROOT))


def sort_key(path: Path) -> tuple[int, str]:
    prefix = path.name.split(" - ", 1)[0].strip()
    if prefix.isdigit():
        return (int(prefix), path.name)
    return (10**9, path.name)


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


def chapter_number_from_path(path: Path) -> int:
    prefix = path.name.split(" - ", 1)[0].strip()
    return int(prefix) if prefix.isdigit() else 0


def build_doc_id_for_pdf(pdf_path: Path) -> str:
    configure_asset_mcp_path()
    from src.application.document_service import build_doc_id_unique_suffix
    from src.domain.value_objects import DocId

    return DocId.generate(
        pdf_path.stem,
        build_doc_id_unique_suffix(pdf_path),
    ).value


def block_has_searchable_text(block: dict[str, Any]) -> bool:
    text = block.get("text")
    return isinstance(text, str) and bool(text.strip())


def assess_source_readiness(blocks: Any) -> tuple[bool, int, int, list[str]]:
    if not isinstance(blocks, list):
        return False, 0, 0, ["blocks.json is not a list"]

    searchable_blocks = [block for block in blocks if isinstance(block, dict) and block_has_searchable_text(block)]
    precise_blocks = [
        block
        for block in searchable_blocks
        if isinstance((block.get("metadata") or {}).get("line_start"), int)
        and isinstance((block.get("metadata") or {}).get("line_end"), int)
        and int(block.get("page") or 0) > 0
    ]

    errors: list[str] = []
    if not searchable_blocks:
        errors.append("blocks.json missing searchable text")
    if not precise_blocks:
        errors.append("blocks.json missing line metadata")

    return not errors, len(searchable_blocks), len(precise_blocks), errors


def count_page_markers(markdown: str) -> tuple[int, int]:
    matches = [int(match.group(1)) for match in PAGE_MARKER_RE.finditer(markdown)]
    if not matches:
        return 0, 0
    return len(matches), max(matches)


def safe_json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_one(pdf_path: Path, data_dir: Path) -> ValidationEntry:
    chapter_number = chapter_number_from_path(pdf_path)
    doc_id = build_doc_id_for_pdf(pdf_path)
    doc_dir = data_dir / doc_id
    manifest_path = doc_dir / f"{doc_id}_manifest.json"
    markdown_path = doc_dir / f"{doc_id}_full.md"
    blocks_path = doc_dir / "blocks.json"

    errors: list[str] = []
    manifest: dict[str, Any] = {}
    blocks: Any = []
    markdown_text = ""

    if not doc_dir.exists():
        errors.append("missing doc directory")
    if not manifest_path.exists():
        errors.append("missing manifest")
    if not markdown_path.exists():
        errors.append("missing markdown")
    if not blocks_path.exists():
        errors.append("missing blocks.json")

    if manifest_path.exists():
        try:
            loaded_manifest = safe_json_load(manifest_path)
            if isinstance(loaded_manifest, dict):
                manifest = loaded_manifest
            else:
                errors.append("manifest is not an object")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"manifest unreadable: {exc}")

    if markdown_path.exists():
        try:
            markdown_text = markdown_path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"markdown unreadable: {exc}")

    if blocks_path.exists():
        try:
            blocks = safe_json_load(blocks_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"blocks unreadable: {exc}")
            blocks = []

    if blocks_path.exists():
        source_ready, searchable_count, precise_count, readiness_errors = assess_source_readiness(blocks)
        errors.extend(readiness_errors)
    else:
        source_ready = False
        searchable_count = 0
        precise_count = 0

    page_marker_count, max_page_marker = count_page_markers(markdown_text)
    manifest_page_count = int(manifest.get("page_count") or 0)

    if markdown_path.exists() and page_marker_count == 0:
        errors.append("markdown missing page markers")
    if manifest_page_count > 0 and max_page_marker > 0 and max_page_marker != manifest_page_count:
        errors.append(
            f"page marker max {max_page_marker} does not match manifest page_count {manifest_page_count}"
        )

    assets = manifest.get("assets") if isinstance(manifest, dict) else {}
    if manifest_path.exists() and not isinstance(assets, dict):
        assets = {}
        errors.append("manifest assets is not an object")
    elif not isinstance(assets, dict):
        assets = {}

    figures = assets.get("figures")
    tables = assets.get("tables")
    kg_entities = manifest.get("lightrag_entities")

    figure_count = len(figures) if isinstance(figures, list) else 0
    table_count = len(tables) if isinstance(tables, list) else 0
    kg_entity_count = len(kg_entities) if isinstance(kg_entities, list) else 0

    return ValidationEntry(
        chapter_number=chapter_number,
        filename=pdf_path.name,
        doc_id=doc_id,
        doc_dir_exists=doc_dir.exists(),
        manifest_exists=manifest_path.exists(),
        markdown_exists=markdown_path.exists(),
        blocks_exists=blocks_path.exists(),
        source_ready=source_ready,
        searchable_block_count=searchable_count,
        precise_block_count=precise_count,
        page_marker_count=page_marker_count,
        max_page_marker=max_page_marker,
        manifest_page_count=manifest_page_count,
        figure_count=figure_count,
        table_count=table_count,
        kg_entity_count=kg_entity_count,
        errors=errors,
    )


def build_summary(entries: list[ValidationEntry]) -> dict[str, Any]:
    return {
        "total": len(entries),
        "doc_dir_exists": sum(1 for entry in entries if entry.doc_dir_exists),
        "manifest_exists": sum(1 for entry in entries if entry.manifest_exists),
        "markdown_exists": sum(1 for entry in entries if entry.markdown_exists),
        "blocks_exists": sum(1 for entry in entries if entry.blocks_exists),
        "source_ready": sum(1 for entry in entries if entry.source_ready),
        "with_page_markers": sum(1 for entry in entries if entry.page_marker_count > 0),
        "with_figures": sum(1 for entry in entries if entry.figure_count > 0),
        "with_tables": sum(1 for entry in entries if entry.table_count > 0),
        "with_kg_entities": sum(1 for entry in entries if entry.kg_entity_count > 0),
        "total_figures": sum(entry.figure_count for entry in entries),
        "total_tables": sum(entry.table_count for entry in entries),
        "total_searchable_blocks": sum(entry.searchable_block_count for entry in entries),
        "total_precise_blocks": sum(entry.precise_block_count for entry in entries),
        "entries_with_errors": sum(1 for entry in entries if entry.errors),
    }


def main() -> int:
    args = parse_args()
    chapter_dir = args.chapter_dir.resolve()
    data_dir = args.data_dir.resolve()
    report_dir = args.report_dir.resolve()

    if not ASSET_MCP_ROOT.exists():
        raise SystemExit(f"Missing asset-aware-mcp clone: {ASSET_MCP_ROOT}")
    if not chapter_dir.exists():
        raise SystemExit(f"Chapter directory not found: {chapter_dir}")

    chapter_pdfs = find_chapter_pdfs(
        chapter_dir=chapter_dir,
        match=args.match,
        limit=args.limit,
        start_chapter=args.start_chapter,
        end_chapter=args.end_chapter,
    )
    if not chapter_pdfs:
        raise SystemExit("No chapter PDFs matched the requested filters.")

    entries = [validate_one(pdf_path, data_dir) for pdf_path in chapter_pdfs]
    summary = build_summary(entries)

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "chapter_dir": str(chapter_dir),
        "data_dir": str(data_dir),
        "requested_match": args.match,
        "requested_limit": args.limit,
        "requested_start_chapter": args.start_chapter,
        "requested_end_chapter": args.end_chapter,
        "summary": summary,
        "entries": [asdict(entry) for entry in entries],
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / (
        "miller_asset_validation_"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps({"summary": summary, "report_path": str(report_path)}, ensure_ascii=False, indent=2))
    return 1 if summary["entries_with_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
