"""
Miller's Anesthesia Chapter 79 提取測試
比較 Marker vs Unstructured 的 section 拆分能力
"""

import fitz
from pathlib import Path

# 檔案路徑
PDF_PATH = Path(r"D:\workspace260203\anesthesia-exam\2020 Miller's Anesthesia 9th.pdf")
OUTPUT_DIR = Path(r"D:\workspace260203\anesthesia-exam\tests\chapter_test")

# Chapter 79: Pediatric and Neonatal Critical Care
# 起始頁 2967 (PDF 頁碼，0-indexed = 2966)
# 假設章節約 30 頁
START_PAGE = 2966  # 0-indexed
END_PAGE = 2996    # 約 30 頁


def extract_chapter():
    """提取 Chapter 79 到新 PDF"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Opening: {PDF_PATH}")
    doc = fitz.open(str(PDF_PATH))
    print(f"Total pages: {len(doc)}")
    
    # 確認頁碼範圍
    if END_PAGE >= len(doc):
        print(f"Warning: END_PAGE {END_PAGE} exceeds document length {len(doc)}")
        end = len(doc) - 1
    else:
        end = END_PAGE
    
    # 提取章節
    new_doc = fitz.open()
    for page_num in range(START_PAGE, end + 1):
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    output_path = OUTPUT_DIR / "ch79_pediatric_critical_care.pdf"
    new_doc.save(str(output_path))
    new_doc.close()
    doc.close()
    
    print(f"✅ Extracted pages {START_PAGE+1}-{end+1} to: {output_path}")
    print(f"   Total extracted: {end - START_PAGE + 1} pages")
    return output_path


if __name__ == "__main__":
    extract_chapter()
