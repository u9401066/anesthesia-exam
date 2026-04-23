"""Manual PDF experiment: compare ch79 ingestion paths.

Usage:
    uv run python scripts/pdf_experiments/ingest_ch79_comparison.py [chapter_pdf]
"""

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_MCP_ROOT = PROJECT_ROOT / "libs" / "asset-aware-mcp"
DEFAULT_CHAPTER_PDF = PROJECT_ROOT / "data" / "manual_pdf_experiments" / "chapter_test" / "ch79_pediatric_critical_care.pdf"
OUTPUT_DIR = PROJECT_ROOT / "data" / "manual_pdf_experiments" / "ingest_comparison"

sys.path.insert(0, str(ASSET_MCP_ROOT))

EXPECTED_SECTIONS = [
    "Relationship Between the Intensive Care Unit and the Operating Room",
    "Family Partnered Care",
    "Disclosure of Medical Errors",
    "Organization of the Pediatric Intensive Care Unit",
    "Cardiovascular System",
    "Common Cardiovascular Disease States",
    "Cardiovascular Pharmacology",
    "Neonatal Resuscitation",
    "Phases of Resuscitation",
    "Interventions During the Cardiac Arrest",
    "Post-resuscitation Myocardial Dysfunction",
    "Ventricular Fibrillation",
    "Respiratory System",
]


def print_section_report(sections, title: str):
    """列印 section 分析報告。"""
    print(f"\n{'=' * 70}")
    print(f"{title} ({len(sections)} found)")
    print("=" * 70)

    for index, section in enumerate(sections, 1):
        level = getattr(section, "level", 1)
        page = getattr(section, "page", "?")
        section_title = getattr(section, "title", str(section))
        level_indent = "  " * (level - 1)
        print(f"  {index:2d}. {level_indent}{'#' * level} {section_title}  (p.{page})")

    titles = [getattr(section, "title", str(section)) for section in sections]
    short_titles = [title for title in titles if len(title) < 15]
    if short_titles:
        print(f"\nShort titles ({len(short_titles)}): {short_titles}")

    levels = {}
    for section in sections:
        level = getattr(section, "level", 1)
        levels[level] = levels.get(level, 0) + 1
    print(f"Level distribution: {dict(sorted(levels.items()))}")

    found_titles_lower = [title.lower() for title in titles]
    matched = 0
    print("\nExpected sections:")
    for expected in EXPECTED_SECTIONS:
        hit = any(expected.lower() in title for title in found_titles_lower)
        if hit:
            matched += 1
        status = "OK" if hit else "MISS"
        print(f"  {status} {expected}")
    percentage = matched / len(EXPECTED_SECTIONS) * 100
    print(f"\nMatch rate: {matched}/{len(EXPECTED_SECTIONS)} ({percentage:.0f}%)")


def run_marker_direct(chapter_pdf: Path):
    """直接用 MarkerPDFExtractor 測試。"""
    print("=" * 70)
    print("Test 1: Marker direct parse for ch79 PDF")
    print("=" * 70)

    if not chapter_pdf.exists():
        print(f"PDF not found: {chapter_pdf}")
        return None

    print(f"PDF: {chapter_pdf}")
    print(f"Size: {chapter_pdf.stat().st_size / 1024:.1f} KB")

    from src.infrastructure.marker_adapter import MarkerPDFExtractor

    extractor = MarkerPDFExtractor()

    print("\nLoading Marker models...")
    start = time.time()
    result = extractor.parse(chapter_pdf)
    elapsed = time.time() - start

    print(f"Marker parse finished ({elapsed:.1f}s)")
    print(f"Markdown: {len(result.markdown)} chars")
    print(f"Blocks: {len(result.blocks)}")
    print(f"TOC items: {len(result.toc)}")
    print(f"Images: {len(result.images)}")
    print(f"Pages: {result.page_count}")

    if result.toc:
        print(f"\nMarker TOC ({len(result.toc)} items):")
        for index, item in enumerate(result.toc, 1):
            title = item.get("title", "?")
            page = item.get("page", "?")
            level = item.get("level", 1)
            indent = "  " * (level - 1)
            print(f"  {index:2d}. {indent}{'#' * level} {title}  (p.{page})")

    section_blocks = [block for block in result.blocks if block.block_type == "SectionHeader"]
    if section_blocks:
        print(f"\nMarker SectionHeader blocks ({len(section_blocks)}):")
        for index, block in enumerate(section_blocks, 1):
            level = block.metadata.get("level", "?")
            print(f"  {index:2d}. [L{level}] {block.text[:80]}  (p.{block.page}, bbox={block.bbox})")

    type_counts = {}
    for block in result.blocks:
        block_type = block.block_type
        type_counts[block_type] = type_counts.get(block_type, 0) + 1
    print(f"\nBlock types: {dict(sorted(type_counts.items(), key=lambda item: -item[1]))}")

    marker_output = OUTPUT_DIR / "marker"
    marker_output.mkdir(parents=True, exist_ok=True)

    md_path = marker_output / "ch79_marker.md"
    md_path.write_text(result.markdown, encoding="utf-8")
    print(f"\nMarkdown saved: {md_path}")

    blocks_data = [
        {
            "block_id": block.block_id,
            "block_type": block.block_type,
            "page": block.page,
            "text": block.text[:500] if block.text else "",
            "bbox": block.bbox,
            "polygon": block.polygon[:4] if block.polygon else [],
            "section_hierarchy": block.section_hierarchy,
            "metadata": block.metadata,
        }
        for block in result.blocks
    ]
    blocks_path = marker_output / "blocks.json"
    blocks_path.write_text(json.dumps(blocks_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Blocks saved: {blocks_path} ({len(blocks_data)} blocks)")

    toc_path = marker_output / "toc.json"
    toc_path.write_text(json.dumps(result.toc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TOC saved: {toc_path}")

    print_section_report(
        [
            type(
                "Section", (), {"title": item.get("title", ""), "level": item.get("level", 1), "page": item.get("page", 0)}
            )()
            for item in result.toc
        ],
        "Marker TOC Sections",
    )

    first_lines = result.markdown.split("\n")[:30]
    print("\nMarker Markdown first 30 lines:")
    for index, line in enumerate(first_lines, 1):
        if line.strip():
            print(f"  {index:3d}: {line[:120]}")

    return result


def run_pymupdf_with_merge(chapter_pdf: Path):
    """用 PyMuPDF + 標題合併後處理做比較。"""
    print(f"\n\n{'=' * 70}")
    print("Test 2: PyMuPDF + heading merge for ch79 PDF")
    print("=" * 70)

    from src.infrastructure.pdf_extractor import PyMuPDFExtractor

    extractor = PyMuPDFExtractor()

    start = time.time()
    markdown = extractor.extract_text(chapter_pdf)
    elapsed = time.time() - start

    print(f"PyMuPDF parse finished ({elapsed:.1f}s)")
    print(f"Markdown: {len(markdown)} chars")

    from src.domain.services import ManifestGenerator

    generator = ManifestGenerator()
    sections = generator._parse_sections(markdown)

    print_section_report(sections, "PyMuPDF + Merge Sections")

    first_lines = markdown.split("\n")[:30]
    print("\nPyMuPDF Markdown first 30 lines:")
    for index, line in enumerate(first_lines, 1):
        if line.strip():
            print(f"  {index:3d}: {line[:120]}")

    pymupdf_output = OUTPUT_DIR / "pymupdf"
    pymupdf_output.mkdir(parents=True, exist_ok=True)
    md_path = pymupdf_output / "ch79_pymupdf.md"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"\nMarkdown saved: {md_path}")

    return sections


def main():
    chapter_pdf = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_CHAPTER_PDF

    if not chapter_pdf.exists():
        print(f"Chapter PDF not found: {chapter_pdf}")
        print(
            "Run 'uv run python scripts/pdf_experiments/extract_chapter_79.py /path/to/2020 Miller's Anesthesia 9th.pdf' first"
        )
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    marker_result = run_marker_direct(chapter_pdf)
    pymupdf_sections = run_pymupdf_with_merge(chapter_pdf)

    print(f"\n\n{'=' * 70}")
    print("Comparison summary")
    print("=" * 70)
    if marker_result:
        print(
            f"Marker: TOC={len(marker_result.toc)} items, "
            f"SectionHeaders={sum(1 for block in marker_result.blocks if block.block_type == 'SectionHeader')}, "
            "blocks.json=ok"
        )
    if pymupdf_sections:
        print(f"PyMuPDF: Sections={len(pymupdf_sections)} (from markdown heading merge)")


if __name__ == "__main__":
    main()