````skill
---
name: source-tracker
description: 來源追蹤器，使用 MCP 工具驗證題目來源真實性。Triggers: 來源追蹤, 追蹤出處, source, 出處, citation, 引用, 來源驗證.
version: 2.0.0
category: quality-control
compatibility:
  - crush
  - claude-code
allowed-tools:
  - search_source_location
  - get_section_content
  - fetch_document_asset
  - inspect_document_manifest
  - exam_get_question
  - exam_update_question
  - exam_mark_validated
---

# 來源追蹤器 (Source Tracker)

## 描述

使用 MCP 工具精準追蹤和驗證題目的出處資訊：
- 驗證頁碼和行號是否真實存在
- 比對原文引用與 PDF 內容
- 標記驗證狀態

**重要：本工具用於驗證已存在的題目，不用於生成題目時的來源追蹤。**

## 觸發條件

- 「來源追蹤」「追蹤出處」
- 「source」「出處」「citation」
- 「來源驗證」「驗證來源」

---

## 🔧 驗證流程

### Step 1: 取得題目資訊

```python
# 取得題目詳情
question = exam_get_question(question_id="abc123")

# 取得來源資訊
source = question["source"]
# {
#   "document": "Miller's Anesthesia 9th Ed",
#   "page": 156,
#   "lines": "12-18",
#   "original_text": "Propofol exerts..."
# }
```

### Step 2: 驗證來源存在

```python
# 使用 asset-aware-mcp 搜尋來源位置
result = search_source_location(
    doc_id="miller9",
    query=source["original_text"][:50],  # 用原文片段搜尋
    block_types=["Text"]
)

# 檢查返回結果
if result["matches"]:
    match = result["matches"][0]
    # 比對頁碼
    if match["page"] == source["page"]:
        verified = True
```

### Step 3: 取得完整內容比對

```python
# 如果需要更詳細的比對
content = get_section_content(
    doc_id="miller9",
    section_id="sec_chapter15"
)

# 檢查原文是否存在於該章節
if source["original_text"] in content:
    text_verified = True
```

### Step 4: 更新驗證狀態

```python
# 標記驗證結果
exam_mark_validated(
    question_id="abc123",
    passed=True,
    notes="來源已驗證：P.156 內容正確"
)
```

---

## 📊 來源結構

### Source Entity（Domain 層定義）

```python
@dataclass
class SourceLocation:
    page: int              # 頁碼 (1-based)
    line_start: int        # 起始行號
    line_end: int          # 結束行號
    bbox: tuple | None     # 位置 (x0, y0, x1, y1)
    original_text: str     # 原文引用

@dataclass
class Source:
    document: str          # 教材名稱
    chapter: str | None    # 章節編號
    section: str | None    # 小節標題
    
    stem_source: SourceLocation | None      # 題幹來源
    answer_source: SourceLocation | None    # 答案依據
    explanation_sources: list[SourceLocation]  # 詳解來源
    
    is_verified: bool = False   # 驗證狀態
    pdf_hash: str | None = None # PDF hash
```

---

## 📝 驗證報告輸出

```
📚 來源驗證報告

題目 ID: abc123
"Propofol 的主要作用機轉是?"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 驗證項目

✅ 文件存在
   doc_id: miller9
   title: Miller's Anesthesia 9th Ed

✅ 頁碼正確
   聲明: P.156
   實際: P.156

✅ 原文比對
   聲明: "Propofol exerts its effects primarily..."
   實際: "Propofol exerts its effects primarily through..."
   匹配度: 100%

✅ 行號範圍
   聲明: L.12-18
   BBox: [72, 340, 520, 380]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 驗證結果: ✅ VERIFIED

已更新 exam_mark_validated(passed=True)
```

---

## ⚠️ 驗證失敗處理

```
❌ 來源驗證失敗

題目 ID: xyz789
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ 問題發現:

1. 頁碼不符
   聲明: P.156
   搜尋結果: 內容位於 P.158

2. 原文不匹配
   聲明: "Propofol is water soluble..."
   實際: 找不到相符內容

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 建議動作:
- [ ] 修正來源頁碼
- [ ] 重新查詢正確來源
- [ ] 標記為待人工審核

已更新 exam_mark_validated(passed=False, notes="...")
```

---

## 🔍 批次驗證

```python
# 批次驗證所有題目
questions = exam_list_questions(limit=100)

results = {
    "verified": [],
    "failed": [],
    "no_source": []
}

for q in questions:
    if not q.get("source"):
        results["no_source"].append(q["id"])
        continue
    
    # 執行驗證流程...
    if verified:
        results["verified"].append(q["id"])
    else:
        results["failed"].append(q["id"])

# 輸出統計
print(f"✅ 已驗證: {len(results['verified'])}")
print(f"❌ 驗證失敗: {len(results['failed'])}")
print(f"⚠️ 無來源: {len(results['no_source'])}")
```

````
