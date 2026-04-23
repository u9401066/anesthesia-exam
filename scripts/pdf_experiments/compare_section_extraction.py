"""Manual PDF experiment: compare Marker vs Unstructured section extraction.

Usage:
    uv run python scripts/pdf_experiments/compare_section_extraction.py [unstructured|marker] [chapter_pdf]
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHAPTER_PDF = PROJECT_ROOT / "data" / "manual_pdf_experiments" / "chapter_test" / "ch79_pediatric_critical_care.pdf"
OUTPUT_DIR = PROJECT_ROOT / "data" / "manual_pdf_experiments" / "section_compare"


def run_unstructured_fast(chapter_pdf: Path):
    """測試 Unstructured (fast 策略，避免 OOM)"""
    print("=" * 60)
    print("Testing Unstructured (fast strategy)")
    print("=" * 60)

    try:
        from unstructured.partition.pdf import partition_pdf

        start = time.time()

        elements = partition_pdf(
            str(chapter_pdf),
            strategy="fast",
        )

        elapsed = time.time() - start
        print(f"Time: {elapsed:.2f}s")
        print(f"Total elements: {len(elements)}")

        type_counts = {}
        for element in elements:
            element_type = type(element).__name__
            type_counts[element_type] = type_counts.get(element_type, 0) + 1

        print("\nElement types:")
        for element_type, count in sorted(type_counts.items(), key=lambda item: -item[1]):
            print(f"   {element_type}: {count}")

        titles = [element for element in elements if type(element).__name__ == "Title"]
        print(f"\nTitles found ({len(titles)}):")
        for index, title in enumerate(titles[:15], 1):
            text = title.text[:80] if len(title.text) > 80 else title.text
            print(f"   {index}. {text}")
        if len(titles) > 15:
            print(f"   ... and {len(titles) - 15} more")

        try:
            from unstructured.chunking.title import chunk_by_title

            chunks = chunk_by_title(elements, max_characters=2000)
            print(f"\nChunks (by title): {len(chunks)}")
            for index, chunk in enumerate(chunks[:5], 1):
                text = chunk.text[:100].replace("\n", " ")
                print(f"   Chunk {index}: {text}...")
        except Exception as error:
            print(f"\nchunk_by_title failed: {error}")

        return elements

    except Exception as error:
        print(f"Unstructured failed: {error}")
        import traceback

        traceback.print_exc()
        return None


def run_marker(chapter_pdf: Path):
    """測試 Marker"""
    print("\n" + "=" * 60)
    print("Testing Marker")
    print("=" * 60)

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        start = time.time()
        print("Loading Marker models (this may take a while)...")

        model_dict = create_model_dict()
        converter = PdfConverter(artifact_dict=model_dict)

        print(f"Model loading: {time.time() - start:.2f}s")

        start = time.time()
        result = converter(str(chapter_pdf))
        elapsed = time.time() - start

        print(f"Conversion: {elapsed:.2f}s")

        markdown = result.markdown
        blocks = result.children if hasattr(result, "children") else []

        print(f"Markdown length: {len(markdown)} chars")
        print(f"Blocks: {len(blocks)}")

        if hasattr(result, "toc") and result.toc:
            print(f"\nTOC ({len(result.toc)} items):")
            for index, item in enumerate(result.toc[:15], 1):
                print(f"   {index}. {item}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        md_path = OUTPUT_DIR / "marker_output.md"
        md_path.write_text(markdown, encoding="utf-8")
        print(f"\nSaved: {md_path}")

        return result

    except ImportError as error:
        print(f"Marker not installed: {error}")
        print("Install with: uv add marker-pdf")
        return None
    except Exception as error:
        print(f"Marker failed: {error}")
        import traceback

        traceback.print_exc()
        return None


def parse_args() -> tuple[str, Path]:
    strategy = "unstructured"
    chapter_pdf = DEFAULT_CHAPTER_PDF
    args = sys.argv[1:]

    if args and args[0] in {"unstructured", "marker"}:
        strategy = args.pop(0)

    if args:
        chapter_pdf = Path(args[0]).expanduser()

    return strategy, chapter_pdf


def main():
    strategy, chapter_pdf = parse_args()

    if not chapter_pdf.exists():
        print(f"Chapter PDF not found: {chapter_pdf}")
        print(
            "Run 'uv run python scripts/pdf_experiments/extract_chapter_79.py /path/to/2020 Miller's Anesthesia 9th.pdf' first"
        )
        return

    print(f"Testing with: {chapter_pdf}")
    print(f"File size: {chapter_pdf.stat().st_size / 1024 / 1024:.2f} MB")

    if strategy == "unstructured":
        run_unstructured_fast(chapter_pdf)
    elif strategy == "marker":
        run_marker(chapter_pdf)
    else:
        print(f"Unknown strategy: {strategy}")
        print("Usage: uv run python scripts/pdf_experiments/compare_section_extraction.py [unstructured|marker] [chapter_pdf]")


if __name__ == "__main__":
    main()