"""
比較 Marker vs Unstructured 的 Section 拆分能力
使用 Chapter 79 (31頁) 作為測試
"""

import sys
import time
from pathlib import Path

CHAPTER_PDF = Path(r"D:\workspace260203\anesthesia-exam\tests\chapter_test\ch79_pediatric_critical_care.pdf")
OUTPUT_DIR = Path(r"D:\workspace260203\anesthesia-exam\tests\chapter_test")


def test_unstructured_fast():
    """測試 Unstructured (fast 策略，避免 OOM)"""
    print("=" * 60)
    print("Testing Unstructured (fast strategy)")
    print("=" * 60)

    try:
        from unstructured.partition.pdf import partition_pdf

        start = time.time()

        # 使用 fast 策略（只用 pdfminer，不載入 ML 模型）
        elements = partition_pdf(
            str(CHAPTER_PDF),
            strategy="fast",  # 避免載入重模型
        )

        elapsed = time.time() - start
        print(f"⏱️ Time: {elapsed:.2f}s")
        print(f"📦 Total elements: {len(elements)}")

        # 統計元素類型
        type_counts = {}
        for el in elements:
            t = type(el).__name__
            type_counts[t] = type_counts.get(t, 0) + 1

        print("\n📊 Element types:")
        for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"   {t}: {count}")

        # 顯示 Title 元素（用於 section 拆分）
        titles = [el for el in elements if type(el).__name__ == "Title"]
        print(f"\n📑 Titles found ({len(titles)}):")
        for i, title in enumerate(titles[:15]):
            text = title.text[:80] if len(title.text) > 80 else title.text
            print(f"   {i + 1}. {text}")
        if len(titles) > 15:
            print(f"   ... and {len(titles) - 15} more")

        # 測試 chunk_by_title
        try:
            from unstructured.chunking.title import chunk_by_title

            chunks = chunk_by_title(elements, max_characters=2000)
            print(f"\n✂️ Chunks (by title): {len(chunks)}")
            for i, chunk in enumerate(chunks[:5]):
                text = chunk.text[:100].replace("\n", " ")
                print(f"   Chunk {i + 1}: {text}...")
        except Exception as e:
            print(f"\n⚠️ chunk_by_title failed: {e}")

        return elements

    except Exception as e:
        print(f"❌ Unstructured failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_marker():
    """測試 Marker"""
    print("\n" + "=" * 60)
    print("Testing Marker")
    print("=" * 60)

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        start = time.time()
        print("📥 Loading Marker models (this may take a while)...")

        # 建立模型（這會載入 GPU/CPU 模型）
        model_dict = create_model_dict()
        converter = PdfConverter(artifact_dict=model_dict)

        print(f"⏱️ Model loading: {time.time() - start:.2f}s")

        # 轉換 PDF
        start = time.time()
        result = converter(str(CHAPTER_PDF))
        elapsed = time.time() - start

        print(f"⏱️ Conversion: {elapsed:.2f}s")

        # 結果分析
        markdown = result.markdown
        blocks = result.children if hasattr(result, "children") else []

        print(f"📝 Markdown length: {len(markdown)} chars")
        print(f"📦 Blocks: {len(blocks)}")

        # 顯示 TOC
        if hasattr(result, "toc") and result.toc:
            print(f"\n📑 TOC ({len(result.toc)} items):")
            for i, item in enumerate(result.toc[:15]):
                print(f"   {i + 1}. {item}")

        # 儲存結果
        md_path = OUTPUT_DIR / "marker_output.md"
        md_path.write_text(markdown, encoding="utf-8")
        print(f"\n💾 Saved: {md_path}")

        return result

    except ImportError as e:
        print(f"⚠️ Marker not installed: {e}")
        print("   Install with: uv add marker-pdf")
        return None
    except Exception as e:
        print(f"❌ Marker failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def main():
    if not CHAPTER_PDF.exists():
        print(f"❌ Chapter PDF not found: {CHAPTER_PDF}")
        print("   Run test_chapter_extraction.py first")
        return

    print(f"📄 Testing with: {CHAPTER_PDF}")
    print(f"   File size: {CHAPTER_PDF.stat().st_size / 1024 / 1024:.2f} MB")

    # 根據參數選擇測試
    if len(sys.argv) > 1:
        if sys.argv[1] == "unstructured":
            test_unstructured_fast()
        elif sys.argv[1] == "marker":
            test_marker()
        else:
            print(f"Unknown test: {sys.argv[1]}")
            print("Usage: python compare_section_extraction.py [unstructured|marker]")
    else:
        # 預設只跑 unstructured（輕量）
        print("\n💡 Tip: Run with 'marker' or 'unstructured' argument")
        print("   Default: unstructured (lightweight)\n")
        test_unstructured_fast()


if __name__ == "__main__":
    main()
