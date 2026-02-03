````skill
---
name: export-formatter
description: 匯出格式器，將試卷匯出為多種格式。Triggers: 匯出, export, 下載, PDF, Word, 列印, 輸出格式.
version: 1.0.0
category: output
compatibility:
  - crush
  - claude-code
allowed-tools:
  - get_exam
  - export_pdf
  - export_docx
  - export_json
---

# 匯出格式器 (Export Formatter)

## 描述

將試卷匯出為多種格式：
- PDF（含答案卷/無答案卷）
- Word/DOCX
- JSON（程式化處理）
- Markdown
- 線上互動格式

## 觸發條件

- 「匯出」「export」「下載」
- 「PDF」「Word」
- 「列印」「輸出格式」

---

## 🔧 匯出流程

### Step 1: 載入試卷

```python
exam = get_exam(exam_id)
```

### Step 2: 選擇匯出格式

```python
formats = {
    "pdf": export_to_pdf,
    "pdf_with_answers": export_to_pdf_with_answers,
    "docx": export_to_docx,
    "json": export_to_json,
    "markdown": export_to_markdown,
    "html": export_to_html,
    "moodle_xml": export_to_moodle  # LMS 整合
}
```

### Step 3: 應用樣式

```python
def apply_template(exam, format, template="default"):
    """套用輸出樣式"""
    
    templates = {
        "default": "標準考卷樣式",
        "formal": "正式考試樣式 (含浮水印)",
        "practice": "練習用樣式 (含解答)",
        "print_friendly": "列印友善 (省墨)"
    }
    
    return render(exam, templates[template])
```

---

## 📊 匯出格式

### PDF 格式

```python
def export_to_pdf(exam, options):
    """匯出為 PDF"""
    
    pdf_options = {
        "page_size": "A4",
        "margins": {"top": 2, "bottom": 2, "left": 2.5, "right": 2},
        "font": "Times New Roman",
        "font_size": 12,
        "include_cover": True,
        "include_answer_sheet": True,
        "watermark": None,  # 可加浮水印
        "header": exam.title,
        "footer": "Page {page} of {total}"
    }
    
    # 生成 PDF
    pdf = PDFDocument()
    pdf.add_cover_page(exam)
    pdf.add_instructions(exam)
    pdf.add_questions(exam.questions)
    
    if options.include_answer_sheet:
        pdf.add_answer_sheet(exam)
    
    return pdf.save(f"{exam.id}.pdf")
```

### Word (DOCX) 格式

```python
def export_to_docx(exam, options):
    """匯出為 Word 文件"""
    
    doc = Document()
    
    # 設定樣式
    doc.styles['Normal'].font.name = '標楷體'
    
    # 封面
    doc.add_heading(exam.title, 0)
    doc.add_paragraph(f"考試日期: {exam.date}")
    doc.add_paragraph(f"考試時間: {exam.duration} 分鐘")
    
    # 題目
    for q in exam.questions:
        doc.add_paragraph(f"{q.number}. {q.stem}")
        for opt in q.options:
            doc.add_paragraph(f"   {opt}")
    
    return doc.save(f"{exam.id}.docx")
```

### JSON 格式

```python
def export_to_json(exam):
    """匯出為 JSON (程式化處理)"""
    
    return {
        "exam_id": exam.id,
        "metadata": exam.metadata,
        "questions": [q.to_dict() for q in exam.questions],
        "answer_key": exam.answer_key,
        "explanations": exam.explanations
    }
```

### Moodle XML 格式

```python
def export_to_moodle(exam):
    """匯出為 Moodle 題庫格式"""
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<quiz>\n'
    
    for q in exam.questions:
        xml += f'''
        <question type="multichoice">
            <name><text>{q.number}</text></name>
            <questiontext format="html">
                <text><![CDATA[{q.stem}]]></text>
            </questiontext>
            ...
        </question>
        '''
    
    xml += '</quiz>'
    return xml
```

---

## 📝 輸出格式選項

```
🖨️ 匯出試卷

試卷: exam_20260203_001
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

選擇匯出格式:

1️⃣ PDF - 考試用
   └── 不含答案，正式考試格式

2️⃣ PDF - 練習用
   └── 含答案和解析

3️⃣ Word (DOCX)
   └── 可編輯格式

4️⃣ JSON
   └── 程式化處理格式

5️⃣ Moodle XML
   └── 可匯入 Moodle/LMS

6️⃣ Markdown
   └── 純文字格式

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 📄 匯出範例

### PDF 考試卷

```
┌────────────────────────────────────────┐
│                                        │
│         麻醉學模擬考                    │
│       靜脈麻醉劑專章                    │
│                                        │
│  考試日期: 2026年2月3日                 │
│  考試時間: 60 分鐘                      │
│  總分: 100 分                          │
│                                        │
│  注意事項:                             │
│  1. 請仔細閱讀題目                      │
│  2. 每題只選一個答案                    │
│  3. 請用 2B 鉛筆作答                   │
│                                        │
├────────────────────────────────────────┤
│                                        │
│  1. Propofol 最主要的心血管副作用是？   │
│                                        │
│     A. 低血壓                          │
│     B. 心搏過速                        │
│     C. 高血壓                          │
│     D. 心室頻脈                        │
│                                        │
│  2. 下列哪種藥物最適合用於顱內壓升高    │
│     的病人進行麻醉誘導？                │
│     ...                                │
│                                        │
└────────────────────────────────────────┘
```

### 答案卷

```
┌────────────────────────────────────────┐
│                                        │
│              答案卷                     │
│                                        │
│  姓名: ____________  座號: _____       │
│                                        │
│  ┌──┬──┬──┬──┬──┬──┬──┬──┬──┬──┐      │
│  │01│02│03│04│05│06│07│08│09│10│      │
│  ├──┼──┼──┼──┼──┼──┼──┼──┼──┼──┤      │
│  │  │  │  │  │  │  │  │  │  │  │      │
│  └──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘      │
│  ...                                   │
│                                        │
└────────────────────────────────────────┘
```

---

## ✅ 匯出完成

```
✅ 匯出成功

格式: PDF (考試用)
檔案: exam_20260203_001.pdf
大小: 2.3 MB
頁數: 12 頁

包含內容:
├── ✓ 封面
├── ✓ 考試說明
├── ✓ 試題 (50題)
├── ✓ 答案卷
└── ✗ 解答 (未包含)

📁 已儲存至: data/exams/exam_20260203_001.pdf
```

````
