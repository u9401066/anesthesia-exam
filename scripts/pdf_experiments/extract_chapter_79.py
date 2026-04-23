"""Manual PDF experiment: extract Chapter 79 from Miller's Anesthesia.

Usage:
    uv run python scripts/pdf_experiments/extract_chapter_79.py "/path/to/2020 Miller's Anesthesia 9th.pdf"
"""

import sys
from pathlib import Path

import fitz

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_PDF = PROJECT_ROOT / "2020 Miller's Anesthesia 9th.pdf"
OUTPUT_DIR = PROJECT_ROOT / "data" / "manual_pdf_experiments" / "chapter_test"

START_PAGE = 2966
END_PAGE = 2996


def extract_chapter(source_pdf: Path) -> Path:
    """提取 Chapter 79 到新 PDF。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Opening: {source_pdf}")
    document = fitz.open(str(source_pdf))
    print(f"Total pages: {len(document)}")

    if END_PAGE >= len(document):
        print(f"Warning: END_PAGE {END_PAGE} exceeds document length {len(document)}")
        end_page = len(document) - 1
    else:
        end_page = END_PAGE

    new_document = fitz.open()
    for page_number in range(START_PAGE, end_page + 1):
        new_document.insert_pdf(document, from_page=page_number, to_page=page_number)

    output_path = OUTPUT_DIR / "ch79_pediatric_critical_care.pdf"
    new_document.save(str(output_path))
    new_document.close()
    document.close()

    print(f"Extracted pages {START_PAGE + 1}-{end_page + 1} to: {output_path}")
    print(f"Total extracted: {end_page - START_PAGE + 1} pages")
    return output_path


def main():
    source_pdf = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_SOURCE_PDF

    if not source_pdf.exists():
        print(f"Source PDF not found: {source_pdf}")
        print(
            "Usage: uv run python scripts/pdf_experiments/extract_chapter_79.py /path/to/2020 Miller's Anesthesia 9th.pdf"
        )
        raise SystemExit(1)

    extract_chapter(source_pdf.resolve())


if __name__ == "__main__":
    main()