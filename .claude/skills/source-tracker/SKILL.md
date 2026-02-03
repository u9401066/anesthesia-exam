````skill
---
name: source-tracker
description: 來源追蹤器，追蹤題目出處並驗證來源存在性。Triggers: 來源追蹤, 追蹤出處, source, 出處, citation, 引用, 來源驗證.
version: 1.0.0
category: quality-control
compatibility:
  - crush
  - claude-code
allowed-tools:
  - source_lookup
  - source_verify
  - get_question
  - update_question
---

# 來源追蹤器 (Source Tracker)

## 描述

精準追蹤題目的出處資訊，包含：
- 教材/文獻名稱
- 頁碼和行號
- 原文引用
- 來源驗證

這是本系統的核心功能，確保每道題目都有可追溯的依據。

## 觸發條件

- 「來源追蹤」「追蹤出處」
- 「source」「出處」
- 「citation」「引用」

---

## 🔧 追蹤流程

### Step 1: 來源結構定義

```python
@dataclass
class Source:
    document: str           # 文件名稱
    document_id: str        # 文件唯一 ID
    page: int              # 頁碼
    lines: tuple[int, int] # (起始行, 結束行)
    original_text: str     # 原文引用
    confidence: float      # 來源信心度
    verified: bool         # 是否已驗證
```

### Step 2: 來源擷取

```python
def extract_source(question, contexts):
    """從生成上下文中擷取來源資訊"""
    
    sources = []
    for ctx in contexts:
        source = Source(
            document=ctx.metadata['document'],
            document_id=ctx.metadata['doc_id'],
            page=ctx.metadata['page'],
            lines=(ctx.metadata['start_line'], ctx.metadata['end_line']),
            original_text=ctx.content[:500],  # 擷取前500字
            confidence=ctx.similarity_score,
            verified=False
        )
        sources.append(source)
    
    return sources
```

### Step 3: 來源驗證

```python
def verify_source(source):
    """驗證來源資訊是否正確"""
    
    # 1. 檢查文件存在
    doc_exists = check_document_exists(source.document_id)
    
    # 2. 檢查頁碼範圍
    page_valid = check_page_valid(source.document_id, source.page)
    
    # 3. 對照原文
    text_match = verify_text_match(
        source.document_id,
        source.page,
        source.lines,
        source.original_text
    )
    
    return doc_exists and page_valid and text_match
```

### Step 4: 生成引用格式

```python
def format_citation(source, style="APA"):
    """生成標準引用格式"""
    
    if style == "APA":
        return f"{source.document}, p.{source.page}, L.{source.lines[0]}-{source.lines[1]}"
    elif style == "IEEE":
        return f"[{source.document_id}] p.{source.page}"
```

---

## 📊 來源報告

```json
{
  "question_id": "q_20260203_001",
  "sources": [
    {
      "type": "primary",
      "document": "Miller's Anesthesia, 9th Ed",
      "document_id": "miller9",
      "page": 542,
      "lines": [15, 28],
      "original_text": "Propofol produces dose-dependent decreases in arterial blood pressure...",
      "confidence": 0.95,
      "verified": true,
      "citation": "Miller's Anesthesia, 9th Ed, p.542, L.15-28"
    },
    {
      "type": "supporting",
      "document": "Miller's Anesthesia, 9th Ed",
      "document_id": "miller9",
      "page": 1823,
      "lines": [5, 12],
      "original_text": "Management of hypotension during anesthesia...",
      "confidence": 0.78,
      "verified": true,
      "citation": "Miller's Anesthesia, 9th Ed, p.1823, L.5-12"
    }
  ],
  "verification_status": "VERIFIED",
  "coverage": 0.92
}
```

---

## 📝 輸出格式

```
📚 來源追蹤報告

題目: q_20260203_001
"Propofol 造成低血壓的主要機制是?"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔗 主要來源 (Primary)

📖 Miller's Anesthesia, 9th Ed
├── 📄 頁碼: P.542
├── 📍 行號: L.15-28
├── 📝 原文: "Propofol produces dose-dependent 
│          decreases in arterial blood pressure
│          primarily through vasodilation..."
├── 📊 信心度: 95%
└── ✅ 驗證: 已確認

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔗 輔助來源 (Supporting)

📖 Miller's Anesthesia, 9th Ed
├── 📄 頁碼: P.1823
├── 📍 行號: L.5-12
├── 📝 原文: "Management of hypotension during
│          anesthesia requires understanding..."
├── 📊 信心度: 78%
└── ✅ 驗證: 已確認

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 引用格式:
APA: Miller's Anesthesia (9th ed.), p.542, L.15-28
IEEE: [Miller9] p.542
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🎯 來源品質指標

| 指標 | 說明 | 目標值 |
| ---- | ---- | ------ |
| 信心度 | 來源與答案的相關性 | >80% |
| 驗證狀態 | 是否通過驗證 | ✅ VERIFIED |
| 覆蓋率 | 答案被來源支持的比例 | >90% |
| 來源數 | 支持該題的來源數量 | ≥1 |

---

## 🔍 批次來源驗證

```python
def batch_verify_sources(questions):
    """批次驗證所有題目的來源"""
    
    results = {
        "verified": [],
        "unverified": [],
        "missing_source": []
    }
    
    for q in questions:
        if not q.sources:
            results["missing_source"].append(q.id)
        elif all(verify_source(s) for s in q.sources):
            results["verified"].append(q.id)
        else:
            results["unverified"].append(q.id)
    
    return results
```

輸出：
```
📊 批次來源驗證報告

總題數: 50

✅ 已驗證: 42 (84%)
⚠️ 待驗證: 5 (10%)
❌ 無來源: 3 (6%)

需要處理:
├── q_20260203_015 - 來源頁碼錯誤
├── q_20260203_023 - 原文不匹配
└── q_20260203_044 - 缺少來源資訊
```

````
