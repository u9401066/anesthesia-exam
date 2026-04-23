"""Batch ingest Miller chapter PDFs through the local asset-aware-mcp clone.

Usage examples:
    uv run python scripts/ingest_miller_chapters.py --limit 1 --match "76 - "
    uv run python scripts/ingest_miller_chapters.py --use-marker --chunk-size 64
    uv run python scripts/ingest_miller_chapters.py --high-fidelity-marker --limit 1 --match "76 - "
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_MCP_ROOT = PROJECT_ROOT / "libs" / "asset-aware-mcp"
DEFAULT_CHAPTER_DIR = PROJECT_ROOT / "Miller anesthesia章節分割版"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "reports"
DEFAULT_MILLER_PROFILE_JSON = (
    PROJECT_ROOT / "configs" / "asset-aware" / "miller_marker_hq.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch ingest Miller chapter PDFs into the repo data directory."
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
        help="Target data directory for asset-aware-mcp output.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory for JSON ingest reports.",
    )
    parser.add_argument(
        "--match",
        default="",
        help="Only ingest chapter files containing this substring.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of chapter PDFs to ingest. 0 means all matched files.",
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
    parser.add_argument(
        "--use-marker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use Marker backend to generate blocks.json.",
    )
    parser.add_argument(
        "--extract-figures",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Extract figure crops when using Marker.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=64,
        help="Marker pages per chunk. 0 means full document.",
    )
    parser.add_argument(
        "--disable-lightrag",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Disable LightRAG during ingestion to avoid unrelated embedding dependencies.",
    )
    parser.add_argument(
        "--skip-ready",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip chapter docs that already have a non-empty blocks.json.",
    )
    parser.add_argument(
        "--fallback-blocks",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate markdown-aligned blocks.json when Marker is unavailable or too heavy.",
    )
    parser.add_argument(
        "--text-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use a lightweight text-first ingest path that skips figure/table extraction.",
    )
    parser.add_argument(
        "--clean-existing",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Delete any existing chapter doc directory before re-ingesting it.",
    )
    parser.add_argument(
        "--require-marker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Fail instead of silently falling back when Marker is requested but unavailable.",
    )
    parser.add_argument(
        "--etl-profile",
        default="",
        help="Built-in asset-aware ETL profile name to activate before ingestion.",
    )
    parser.add_argument(
        "--etl-profile-json",
        type=Path,
        default=None,
        help="Custom ETL profile JSON file to load and activate before ingestion.",
    )
    parser.add_argument(
        "--high-fidelity-marker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Recommended Miller textbook mode: strict Marker + figures + custom profile.",
    )
    return parser.parse_args()


def configure_asset_mcp_env(
    data_dir: Path,
    disable_lightrag: bool,
    *,
    etl_profile: str = "",
    etl_profile_json: Path | None = None,
) -> None:
    os.environ["DATA_DIR"] = str(data_dir)
    if disable_lightrag:
        os.environ["ENABLE_LIGHTRAG"] = "false"
    if etl_profile:
        os.environ["ETL_PROFILE"] = etl_profile
    if etl_profile_json is not None:
        os.environ["ETL_PROFILE_JSON"] = str(etl_profile_json.resolve())
    sys.path.insert(0, str(ASSET_MCP_ROOT))


def activate_asset_mcp_profile(
    *,
    etl_profile: str = "",
    etl_profile_json: Path | None = None,
) -> str:
    if not etl_profile and etl_profile_json is None:
        return ""

    from src.domain.etl_profile import ETLProfileRegistry
    from src.presentation.dependencies import rebuild_for_profile

    if etl_profile_json is not None:
        loaded_profile = ETLProfileRegistry.load_from_json(etl_profile_json.resolve())
        rebuild_for_profile(loaded_profile.name)
        return loaded_profile.name

    rebuild_for_profile(etl_profile)
    return etl_profile


def build_doc_id_for_pdf(pdf_path: Path) -> str:
    from src.application.document_service import build_doc_id_unique_suffix
    from src.domain.value_objects import DocId

    return DocId.generate(
        pdf_path.stem,
        build_doc_id_unique_suffix(pdf_path),
    ).value


def find_chapter_pdfs(
    chapter_dir: Path,
    match: str,
    limit: int,
    start_chapter: int,
    end_chapter: int,
) -> list[Path]:
    def sort_key(path: Path) -> tuple[int, str]:
        prefix = path.name.split(" - ", 1)[0].strip()
        if prefix.isdigit():
            return (int(prefix), path.name)
        return (10**9, path.name)

    pdfs = [
        path
        for path in sorted(chapter_dir.glob("*.pdf"), key=sort_key)
        if not path.name.startswith("._")
    ]
    if start_chapter > 0 or end_chapter > 0:
        filtered: list[Path] = []
        for path in pdfs:
            prefix = path.name.split(" - ", 1)[0].strip()
            if not prefix.isdigit():
                continue
            chapter_number = int(prefix)
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


@dataclass
class IngestEntry:
    filename: str
    pdf_path: str
    doc_id: str
    skipped: bool
    success: bool
    backend: str
    has_blocks_json: bool
    blocks_count: int
    error: str


def check_blocks_json(data_dir: Path, doc_id: str) -> tuple[bool, int]:
    blocks_path = data_dir / doc_id / "blocks.json"
    if not blocks_path.exists():
        return False, 0

    try:
        payload = json.loads(blocks_path.read_text(encoding="utf-8"))
    except Exception:
        return True, 0

    if isinstance(payload, list):
        return True, len(payload)
    return True, 0


def load_existing_readiness(data_dir: Path, doc_id: str) -> tuple[bool, int]:
    return check_blocks_json(data_dir, doc_id)


def _is_page_marker(line: str) -> bool:
    return bool(re.match(r"^\s*<!--\s*Page\s+\d+\s*-->\s*$", line))


def _extract_page_number(line: str) -> int | None:
    match = re.match(r"^\s*<!--\s*Page\s+(\d+)\s*-->\s*$", line)
    return int(match.group(1)) if match else None


def _clean_visible_text(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^\*+|\*+$", "", cleaned).strip()
    return cleaned


def _looks_like_standalone_header(line: str) -> tuple[bool, int, str]:
    stripped = line.strip()
    markdown_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
    if markdown_match:
        return True, len(markdown_match.group(1)), _clean_visible_text(markdown_match.group(2))

    if not (stripped.startswith("**") and stripped.endswith("**")):
        return False, 0, ""

    title = _clean_visible_text(stripped)
    if not title:
        return False, 0, ""
    if title.isdigit():
        return False, 0, ""
    if len(title) > 120:
        return False, 0, ""
    if title.lower().startswith("downloaded for "):
        return False, 0, ""

    return True, 4, title


def _should_skip_content_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if _is_page_marker(stripped):
        return True
    if stripped.lower().startswith("downloaded for "):
        return True
    if "clinicalkey.com" in stripped.lower():
        return True
    return False


def build_fallback_blocks(markdown: str) -> list[dict[str, object]]:
    lines = markdown.splitlines()
    blocks: list[dict[str, object]] = []
    page_number = 1
    source_order = 0
    active_sections: dict[int, str] = {}
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        marker_page = _extract_page_number(raw_line)
        if marker_page is not None:
            page_number = marker_page
            index += 1
            continue

        if _should_skip_content_line(raw_line):
            index += 1
            continue

        is_header, level, title = _looks_like_standalone_header(raw_line)
        if is_header:
            source_order += 1
            active_sections = {
                existing_level: existing_title
                for existing_level, existing_title in active_sections.items()
                if existing_level < level
            }
            active_sections[level] = title
            blocks.append(
                {
                    "block_id": f"blk_{source_order:04d}",
                    "block_type": "SectionHeader",
                    "page": page_number,
                    "text": title,
                    "bbox": [],
                    "polygon": [],
                    "section_hierarchy": {
                        str(section_level): section_title
                        for section_level, section_title in sorted(active_sections.items())
                    },
                    "metadata": {
                        "id": "",
                        "level": level,
                        "source_order": source_order,
                        "fallback_source": "markdown-page-alignment",
                        "line_start": index,
                        "line_end": index + 1,
                        "line_match_strategy": "page-section",
                        "line_match_confidence": 0.95,
                        "matched_section_title": title,
                    },
                }
            )
            index += 1
            continue

        paragraph_start = index
        paragraph_lines: list[str] = []
        while index < len(lines):
            current_line = lines[index]
            if _extract_page_number(current_line) is not None:
                break
            if _should_skip_content_line(current_line):
                if paragraph_lines:
                    break
                index += 1
                paragraph_start = index
                continue
            paragraph_is_header, _, _ = _looks_like_standalone_header(current_line)
            if paragraph_is_header:
                break
            paragraph_lines.append(current_line.strip())
            index += 1

        paragraph_text = " ".join(line for line in paragraph_lines if line).strip()
        if not paragraph_text:
            continue

        source_order += 1
        current_section_title = next(
            reversed(list(sorted(active_sections.items()))),
            (0, ""),
        )[1]
        blocks.append(
            {
                "block_id": f"blk_{source_order:04d}",
                "block_type": "Text",
                "page": page_number,
                "text": paragraph_text[:4000],
                "bbox": [],
                "polygon": [],
                "section_hierarchy": {
                    str(section_level): section_title
                    for section_level, section_title in sorted(active_sections.items())
                },
                "metadata": {
                    "id": "",
                    "level": None,
                    "source_order": source_order,
                    "fallback_source": "markdown-page-alignment",
                    "line_start": paragraph_start,
                    "line_end": index,
                    "line_match_strategy": "page-section",
                    "line_match_confidence": 0.95,
                    "matched_section_title": current_section_title,
                },
            }
        )

    return blocks


def materialize_fallback_blocks(data_dir: Path, doc_id: str) -> tuple[bool, int]:
    doc_dir = data_dir / doc_id
    markdown_path = doc_dir / f"{doc_id}_full.md"
    if not markdown_path.exists():
        return False, 0

    markdown = markdown_path.read_text(encoding="utf-8")
    blocks = build_fallback_blocks(markdown)
    if not blocks:
        return False, 0

    blocks_path = doc_dir / "blocks.json"
    blocks_path.write_text(
        json.dumps(blocks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True, len(blocks)


def ingest_text_only_document(
    pdf_path: Path,
    *,
    data_dir: Path,
) -> tuple[str, str]:
    from src.application.document_service import build_doc_id_unique_suffix
    from src.domain.services import ManifestGenerator
    from src.domain.value_objects import DocId
    from src.infrastructure.file_storage import FileStorage
    from src.infrastructure.pdf_extractor import PyMuPDFExtractor

    repository = FileStorage(data_dir)
    extractor = PyMuPDFExtractor()
    manifest_generator = ManifestGenerator()

    doc_id = DocId.generate(
        pdf_path.stem,
        build_doc_id_unique_suffix(pdf_path),
    ).value
    doc_dir = repository.get_doc_dir(doc_id)
    shutil.copy2(pdf_path, doc_dir / "original.pdf")

    markdown = extractor.extract_text(pdf_path)
    markdown_path = repository.save_markdown(doc_id, markdown)
    page_count = extractor.get_page_count(pdf_path)
    pdf_title = extractor.get_title(pdf_path) if hasattr(extractor, "get_title") else ""

    manifest = manifest_generator.generate(
        doc_id=doc_id,
        filename=pdf_path.name,
        markdown=markdown,
        figures=[],
        tables=[],
        page_count=page_count,
        markdown_path=str(markdown_path),
        pdf_title=pdf_title,
    )
    repository.save_manifest(manifest)
    return doc_id, "pymupdf-text-only"


async def ingest_one(
    pdf_path: Path,
    *,
    data_dir: Path,
    use_marker: bool,
    require_marker: bool,
    extract_figures: bool,
    chunk_size: int,
    skip_ready: bool,
    fallback_blocks: bool,
    text_only: bool,
    clean_existing: bool,
) -> IngestEntry:
    from src.infrastructure.file_storage import FileStorage
    from src.presentation.dependencies import document_service, get_marker_extractor

    doc_id = build_doc_id_for_pdf(pdf_path)
    repository = FileStorage(data_dir)

    if clean_existing and repository.document_exists(doc_id):
        repository.delete_document(doc_id)

    has_blocks, block_count = load_existing_readiness(data_dir, doc_id)
    if skip_ready and has_blocks and block_count > 0:
        return IngestEntry(
            filename=pdf_path.name,
            pdf_path=str(pdf_path),
            doc_id=doc_id,
            skipped=True,
            success=True,
            backend="marker" if use_marker else "pymupdf",
            has_blocks_json=True,
            blocks_count=block_count,
            error="",
        )

    if text_only:
        text_doc_id, backend_name = ingest_text_only_document(
            pdf_path,
            data_dir=data_dir,
        )
        has_blocks, block_count = (
            materialize_fallback_blocks(data_dir, text_doc_id)
            if fallback_blocks
            else check_blocks_json(data_dir, text_doc_id)
        )
        return IngestEntry(
            filename=pdf_path.name,
            pdf_path=str(pdf_path),
            doc_id=text_doc_id,
            skipped=False,
            success=True,
            backend=f"{backend_name}+fallback-blocks" if has_blocks else backend_name,
            has_blocks_json=has_blocks,
            blocks_count=block_count,
            error="",
        )

    ingest_backend = use_marker
    if use_marker and document_service.marker_extractor is None:
        try:
            document_service.marker_extractor = get_marker_extractor()
        except Exception as exc:
            if require_marker:
                return IngestEntry(
                    filename=pdf_path.name,
                    pdf_path=str(pdf_path),
                    doc_id=doc_id,
                    skipped=False,
                    success=False,
                    backend="marker",
                    has_blocks_json=False,
                    blocks_count=0,
                    error=f"Marker unavailable: {exc}",
                )
            ingest_backend = False

    results = await document_service.ingest(
        [str(pdf_path)],
        use_marker=ingest_backend,
        marker_max_pages_per_chunk=chunk_size,
        extract_figures=extract_figures,
    )
    result = results[0]
    has_blocks, block_count = check_blocks_json(data_dir, result.doc_id or doc_id)
    backend_name = result.backend

    if result.success and fallback_blocks and not has_blocks:
        has_blocks, block_count = materialize_fallback_blocks(
            data_dir,
            result.doc_id or doc_id,
        )
        if has_blocks:
            backend_name = (
                "marker" if backend_name == "marker" else "pymupdf+fallback-blocks"
            )

    if not result.success and use_marker and fallback_blocks and not require_marker:
        fallback_results = await document_service.ingest(
            [str(pdf_path)],
            use_marker=False,
        )
        fallback_result = fallback_results[0]
        if fallback_result.success:
            result = fallback_result
            has_blocks, block_count = materialize_fallback_blocks(
                data_dir,
                result.doc_id or doc_id,
            )
            backend_name = "pymupdf+fallback-blocks" if has_blocks else result.backend

    return IngestEntry(
        filename=pdf_path.name,
        pdf_path=str(pdf_path),
        doc_id=result.doc_id or doc_id,
        skipped=False,
        success=bool(result.success),
        backend=backend_name,
        has_blocks_json=has_blocks,
        blocks_count=block_count,
        error=result.error or "",
    )


async def main_async(args: argparse.Namespace) -> int:
    if args.high_fidelity_marker:
        args.use_marker = True
        args.require_marker = True
        args.extract_figures = True
        args.text_only = False
        args.fallback_blocks = False
        if args.chunk_size == 64:
            args.chunk_size = 12
        if not args.etl_profile and args.etl_profile_json is None:
            args.etl_profile_json = DEFAULT_MILLER_PROFILE_JSON

    configure_asset_mcp_env(
        args.data_dir.resolve(),
        args.disable_lightrag,
        etl_profile=args.etl_profile,
        etl_profile_json=args.etl_profile_json,
    )

    chapter_dir = args.chapter_dir.resolve()
    data_dir = args.data_dir.resolve()
    report_dir = args.report_dir.resolve()

    if not ASSET_MCP_ROOT.exists():
        raise SystemExit(f"Missing asset-aware-mcp clone: {ASSET_MCP_ROOT}")
    if not chapter_dir.exists():
        raise SystemExit(f"Chapter directory not found: {chapter_dir}")

    chapter_pdfs = find_chapter_pdfs(
        chapter_dir,
        args.match,
        args.limit,
        args.start_chapter,
        args.end_chapter,
    )
    if not chapter_pdfs:
        raise SystemExit("No chapter PDFs matched the requested filters.")

    activated_profile = activate_asset_mcp_profile(
        etl_profile=args.etl_profile,
        etl_profile_json=args.etl_profile_json,
    )

    report_dir.mkdir(parents=True, exist_ok=True)

    entries: list[IngestEntry] = []
    for index, pdf_path in enumerate(chapter_pdfs, start=1):
        print(f"[{index}/{len(chapter_pdfs)}] ingesting {pdf_path.name}", flush=True)
        try:
            entry = await ingest_one(
                pdf_path,
                data_dir=data_dir,
                use_marker=args.use_marker,
                require_marker=args.require_marker,
                extract_figures=args.extract_figures,
                chunk_size=args.chunk_size,
                skip_ready=args.skip_ready,
                fallback_blocks=args.fallback_blocks,
                text_only=args.text_only,
                clean_existing=args.clean_existing,
            )
        except Exception as exc:  # pragma: no cover - operational path
            entry = IngestEntry(
                filename=pdf_path.name,
                pdf_path=str(pdf_path),
                doc_id=build_doc_id_for_pdf(pdf_path),
                skipped=False,
                success=False,
                backend="marker" if args.use_marker else "pymupdf",
                has_blocks_json=False,
                blocks_count=0,
                error=str(exc),
            )

        status = "ok" if entry.success else "failed"
        if entry.skipped:
            status = "skipped"
        print(
            f"  -> {status}: doc_id={entry.doc_id} blocks={entry.blocks_count} error={entry.error}",
            flush=True,
        )
        entries.append(entry)

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "chapter_dir": str(chapter_dir),
        "data_dir": str(data_dir),
        "use_marker": args.use_marker,
        "require_marker": args.require_marker,
        "high_fidelity_marker": args.high_fidelity_marker,
        "extract_figures": args.extract_figures,
        "chunk_size": args.chunk_size,
        "disable_lightrag": args.disable_lightrag,
        "etl_profile": args.etl_profile,
        "etl_profile_json": str(args.etl_profile_json.resolve()) if args.etl_profile_json else "",
        "activated_profile": activated_profile,
        "skip_ready": args.skip_ready,
        "fallback_blocks": args.fallback_blocks,
        "text_only": args.text_only,
        "clean_existing": args.clean_existing,
        "requested_match": args.match,
        "requested_limit": args.limit,
        "requested_start_chapter": args.start_chapter,
        "requested_end_chapter": args.end_chapter,
        "counts": {
            "total": len(entries),
            "success": sum(1 for entry in entries if entry.success),
            "failed": sum(1 for entry in entries if not entry.success),
            "skipped": sum(1 for entry in entries if entry.skipped),
            "with_blocks": sum(1 for entry in entries if entry.has_blocks_json),
        },
        "entries": [asdict(entry) for entry in entries],
    }

    report_path = report_dir / (
        "miller_ingest_"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"report written to {report_path}", flush=True)

    return 1 if report["counts"]["failed"] else 0


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
