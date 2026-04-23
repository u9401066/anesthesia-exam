"""Refresh Miller chapter figure assets with the local asset-aware image pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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
DEFAULT_PROFILE_JSON = (
    PROJECT_ROOT / "configs" / "asset-aware" / "miller_marker_hq.json"
)


@dataclass
class RefreshEntry:
    filename: str
    doc_id: str
    success: bool
    figure_count: int
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh figure assets for split Miller chapter PDFs."
    )
    parser.add_argument("--chapter-dir", type=Path, default=DEFAULT_CHAPTER_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--match", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-chapter", type=int, default=0)
    parser.add_argument("--end-chapter", type=int, default=0)
    parser.add_argument(
        "--etl-profile-json",
        type=Path,
        default=DEFAULT_PROFILE_JSON,
        help="Custom ETL profile JSON file for figure extraction thresholds.",
    )
    return parser.parse_args()


def configure_asset_mcp_env(data_dir: Path, etl_profile_json: Path | None) -> None:
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["ENABLE_LIGHTRAG"] = "false"
    if etl_profile_json is not None:
        os.environ["ETL_PROFILE_JSON"] = str(etl_profile_json.resolve())
    sys.path.insert(0, str(ASSET_MCP_ROOT))


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


def build_doc_id_for_pdf(pdf_path: Path) -> str:
    from src.application.document_service import build_doc_id_unique_suffix
    from src.domain.value_objects import DocId

    return DocId.generate(
        pdf_path.stem,
        build_doc_id_unique_suffix(pdf_path),
    ).value


async def refresh_one(
    pdf_path: Path,
    *,
    data_dir: Path,
    etl_profile_json: Path | None,
) -> RefreshEntry:
    from src.application.document_service import DocumentService
    from src.domain.etl_profile import ETLProfile
    from src.infrastructure.file_storage import FileStorage
    from src.infrastructure.pdf_extractor import PyMuPDFExtractor

    doc_id = build_doc_id_for_pdf(pdf_path)
    doc_dir = data_dir / doc_id
    manifest_path = doc_dir / f"{doc_id}_manifest.json"
    if not manifest_path.exists():
        return RefreshEntry(
            filename=pdf_path.name,
            doc_id=doc_id,
            success=False,
            figure_count=0,
            error="manifest missing",
        )

    profile = (
        ETLProfile.from_json(etl_profile_json)
        if etl_profile_json is not None
        else ETLProfile.default()
    )
    repository = FileStorage(data_dir)
    extractor = PyMuPDFExtractor(profile=profile)
    service = DocumentService(
        repository=repository,
        pdf_extractor=extractor,
        knowledge_graph=None,
        profile=profile,
    )

    original_pdf = doc_dir / "original.pdf"
    source_pdf = original_pdf if original_pdf.exists() else pdf_path

    images_dir = doc_dir / "images"
    if images_dir.exists():
        shutil.rmtree(images_dir)

    try:
        figures = await service._extract_and_save_images(doc_id, source_pdf)
    except Exception as exc:  # pragma: no cover - operational path
        return RefreshEntry(
            filename=pdf_path.name,
            doc_id=doc_id,
            success=False,
            figure_count=0,
            error=str(exc),
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest.get("assets")
    if not isinstance(assets, dict):
        assets = {}
        manifest["assets"] = assets
    assets["figures"] = [figure.model_dump(mode="json") for figure in figures]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return RefreshEntry(
        filename=pdf_path.name,
        doc_id=doc_id,
        success=True,
        figure_count=len(figures),
        error="",
    )


async def main_async(args: argparse.Namespace) -> int:
    configure_asset_mcp_env(args.data_dir.resolve(), args.etl_profile_json)
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

    report_dir.mkdir(parents=True, exist_ok=True)
    entries: list[RefreshEntry] = []

    for index, pdf_path in enumerate(chapter_pdfs, start=1):
        print(f"[{index}/{len(chapter_pdfs)}] refresh figures {pdf_path.name}", flush=True)
        entry = await refresh_one(
            pdf_path,
            data_dir=data_dir,
            etl_profile_json=args.etl_profile_json,
        )
        status = "ok" if entry.success else "failed"
        print(
            f"  -> {status}: doc_id={entry.doc_id} figures={entry.figure_count} error={entry.error}",
            flush=True,
        )
        entries.append(entry)

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "chapter_dir": str(chapter_dir),
        "data_dir": str(data_dir),
        "etl_profile_json": str(args.etl_profile_json.resolve()) if args.etl_profile_json else "",
        "requested_match": args.match,
        "requested_limit": args.limit,
        "requested_start_chapter": args.start_chapter,
        "requested_end_chapter": args.end_chapter,
        "counts": {
            "total": len(entries),
            "success": sum(1 for entry in entries if entry.success),
            "failed": sum(1 for entry in entries if not entry.success),
            "figures": sum(entry.figure_count for entry in entries),
        },
        "entries": [asdict(entry) for entry in entries],
    }
    report_path = report_dir / (
        "miller_figure_refresh_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json"
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
