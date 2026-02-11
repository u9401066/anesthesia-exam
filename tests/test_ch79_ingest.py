"""
測試 asset-aware-mcp 能否正確拆解 ch79 PDF。

使用 Marker 路徑 (use_marker=True) 來 ingest ch79_pediatric_critical_care.pdf，
Marker 會產生 blocks.json（含 bbox + section_hierarchy），
讓 list_section_tree, search_sections, search_source_location 等工具都能用。

同時也跑 PyMuPDF 路徑做比較。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# 加入 asset-aware-mcp 路徑
ASSET_MCP_ROOT = Path(r"D:\workspace260203\anesthesia-exam\libs\asset-aware-mcp")
sys.path.insert(0, str(ASSET_MCP_ROOT))

# 測試用路徑
CHAPTER_PDF = Path(r"D:\workspace260203\anesthesia-exam\tests\chapter_test\ch79_pediatric_critical_care.pdf")
OUTPUT_DIR = Path(r"D:\workspace260203\anesthesia-exam\tests\chapter_test\output")

# 預期的主要 sections (ch79 的 H2 標題)
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
    """列印 section 分析報告"""
    print(f"\n{'=' * 70}")
    print(f"📑 {title} ({len(sections)} found)")
    print("=" * 70)

    for i, sec in enumerate(sections, 1):
        level = getattr(sec, 'level', 1)
        page = getattr(sec, 'page', '?')
        sec_title = getattr(sec, 'title', str(sec))
        level_indent = "  " * (level - 1)
        print(f"  {i:2d}. {level_indent}{'#' * level} {sec_title}  (p.{page})")

    # 品質檢查
    titles = [getattr(s, 'title', str(s)) for s in sections]

    # 短標題
    short = [t for t in titles if len(t) < 15]
    if short:
        print(f"\n  ⚠️  短標題 ({len(short)}): {short}")

    # 層級分佈
    levels = {}
    for s in sections:
        lv = getattr(s, 'level', 1)
        levels[lv] = levels.get(lv, 0) + 1
    print(f"  📊 層級: {dict(sorted(levels.items()))}")

    # 預期比對
    found_titles_lower = [t.lower() for t in titles]
    matched = 0
    print(f"\n  📋 預期 sections 比對:")
    for exp in EXPECTED_SECTIONS:
        hit = any(exp.lower() in t for t in found_titles_lower)
        if hit:
            matched += 1
        status = "✅" if hit else "❌"
        print(f"    {status} {exp}")
    pct = matched / len(EXPECTED_SECTIONS) * 100
    print(f"\n  🎯 匹配率: {matched}/{len(EXPECTED_SECTIONS)} ({pct:.0f}%)")


def test_marker_direct():
    """直接用 MarkerPDFExtractor 測試 (不走 DocumentService，避免 lightrag 依賴)"""
    print("=" * 70)
    print("Test 1: Marker 直接解析 ch79 PDF")
    print("=" * 70)

    if not CHAPTER_PDF.exists():
        print(f"❌ PDF not found: {CHAPTER_PDF}")
        return None

    print(f"📄 PDF: {CHAPTER_PDF}")
    print(f"   Size: {CHAPTER_PDF.stat().st_size / 1024:.1f} KB")

    from src.infrastructure.marker_adapter import MarkerPDFExtractor

    extractor = MarkerPDFExtractor()

    print("\n🔄 Loading Marker models...")
    start = time.time()

    result = extractor.parse(CHAPTER_PDF)

    elapsed = time.time() - start
    print(f"✅ Marker 解析完成! ({elapsed:.1f}s)")
    print(f"   Markdown: {len(result.markdown)} chars")
    print(f"   Blocks: {len(result.blocks)}")
    print(f"   TOC items: {len(result.toc)}")
    print(f"   Images: {len(result.images)}")
    print(f"   Pages: {result.page_count}")

    # 分析 TOC
    if result.toc:
        print(f"\n📑 Marker TOC ({len(result.toc)} items):")
        for i, item in enumerate(result.toc, 1):
            title = item.get('title', '?')
            page = item.get('page', '?')
            level = item.get('level', 1)
            indent = "  " * (level - 1)
            print(f"  {i:2d}. {indent}{'#' * level} {title}  (p.{page})")

    # 分析 SectionHeader blocks
    section_blocks = [b for b in result.blocks if b.block_type == "SectionHeader"]
    if section_blocks:
        print(f"\n📑 Marker SectionHeader blocks ({len(section_blocks)}):")
        for i, b in enumerate(section_blocks, 1):
            level = b.metadata.get('level', '?')
            print(f"  {i:2d}. [L{level}] {b.text[:80]}  (p.{b.page}, bbox={b.bbox})")

    # Block type 分佈
    type_counts = {}
    for b in result.blocks:
        t = b.block_type
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"\n📊 Block types: {dict(sorted(type_counts.items(), key=lambda x: -x[1]))}")

    # 儲存結果
    marker_output = OUTPUT_DIR / "marker"
    marker_output.mkdir(parents=True, exist_ok=True)

    # 儲存 markdown
    md_path = marker_output / "ch79_marker.md"
    md_path.write_text(result.markdown, encoding="utf-8")
    print(f"\n💾 Markdown saved: {md_path}")

    # 儲存 blocks.json
    blocks_data = [
        {
            "block_id": b.block_id,
            "block_type": b.block_type,
            "page": b.page,
            "text": b.text[:500] if b.text else "",
            "bbox": b.bbox,
            "polygon": b.polygon[:4] if b.polygon else [],
            "section_hierarchy": b.section_hierarchy,
            "metadata": b.metadata,
        }
        for b in result.blocks
    ]
    blocks_path = marker_output / "blocks.json"
    blocks_path.write_text(json.dumps(blocks_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 Blocks saved: {blocks_path} ({len(blocks_data)} blocks)")

    # 儲存 TOC
    toc_path = marker_output / "toc.json"
    toc_path.write_text(json.dumps(result.toc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 TOC saved: {toc_path}")

    # 預期比對
    print_section_report(
        [type('S', (), {'title': item.get('title',''), 'level': item.get('level',1), 'page': item.get('page',0)})()
         for item in result.toc],
        "Marker TOC Sections"
    )

    # 也看 markdown 頭 30 行
    first_lines = result.markdown.split('\n')[:30]
    print(f"\n📝 Marker Markdown 前 30 行:")
    for i, line in enumerate(first_lines, 1):
        if line.strip():
            print(f"  {i:3d}: {line[:120]}")

    return result


def test_pymupdf_with_merge():
    """用 PyMuPDF + 標題合併後處理做比較"""
    print(f"\n\n{'=' * 70}")
    print("Test 2: PyMuPDF + heading merge 解析 ch79 PDF")
    print("=" * 70)

    from src.infrastructure.pdf_extractor import PyMuPDFExtractor

    extractor = PyMuPDFExtractor()

    start = time.time()
    markdown = extractor.extract_text(CHAPTER_PDF)
    elapsed = time.time() - start

    print(f"✅ PyMuPDF 解析完成! ({elapsed:.1f}s)")
    print(f"   Markdown: {len(markdown)} chars")

    # 用 ManifestGenerator 解析 sections
    from src.domain.services import ManifestGenerator

    gen = ManifestGenerator()
    sections = gen._parse_sections(markdown)

    print_section_report(sections, "PyMuPDF + Merge Sections")

    # Markdown 頭 30 行
    first_lines = markdown.split('\n')[:30]
    print(f"\n📝 PyMuPDF Markdown 前 30 行:")
    for i, line in enumerate(first_lines, 1):
        if line.strip():
            print(f"  {i:3d}: {line[:120]}")

    # 儲存
    pymupdf_output = OUTPUT_DIR / "pymupdf"
    pymupdf_output.mkdir(parents=True, exist_ok=True)
    md_path = pymupdf_output / "ch79_pymupdf.md"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"\n💾 Markdown saved: {md_path}")

    return sections


def main():
    if not CHAPTER_PDF.exists():
        print(f"❌ Chapter PDF not found: {CHAPTER_PDF}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Test 1: Marker (主要路徑)
    marker_result = test_marker_direct()

    # Test 2: PyMuPDF + merge (比較路徑)
    pymupdf_sections = test_pymupdf_with_merge()

    # 總結
    print(f"\n\n{'=' * 70}")
    print("📊 總結比較")
    print("=" * 70)
    if marker_result:
        print(f"  Marker:  TOC={len(marker_result.toc)} items, "
              f"SectionHeaders={sum(1 for b in marker_result.blocks if b.block_type == 'SectionHeader')}, "
              f"blocks.json=✅")
    if pymupdf_sections:
        print(f"  PyMuPDF: Sections={len(pymupdf_sections)} (from markdown heading merge)")


if __name__ == "__main__":
    main()
