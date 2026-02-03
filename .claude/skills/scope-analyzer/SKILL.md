````skill
---
name: scope-analyzer
description: 分析出題範圍，識別章節、主題、知識點分佈。Triggers: 分析範圍, 範圍分析, scope, 章節分析, 主題分析, 知識點, analyze scope, 出題範圍.
version: 1.0.0
category: knowledge-processing
compatibility:
  - crush
  - claude-code
allowed-tools:
  - read_file
  - grep_search
  - source_lookup
---

# 範圍分析器 (Scope Analyzer)

## 描述

分析指定的出題範圍，識別章節結構、主題分佈，計算各知識點的權重以指導出題。

## 觸發條件

- 「分析範圍」「範圍分析」
- 「這個章節有哪些重點」
- 「analyze scope」

---

## 🔧 分析流程

### Step 1: 範圍識別

```python
# 解析用戶指定的範圍
scope = parse_scope(user_input)
# 例如: "藥理學第三章" → {book: "藥理學", chapter: 3}
# 例如: "Propofol 相關" → {topic: "Propofol"}
```

### Step 2: 結構分析

```python
# 從索引中提取範圍內的結構
structure = {
    "chapters": [],
    "sections": [],
    "topics": [],
    "key_concepts": []
}

for chunk in index.query(scope):
    structure.chapters.add(chunk.chapter)
    structure.sections.add(chunk.section)
    structure.topics.extend(extract_topics(chunk))
```

### Step 3: 權重計算

```python
# 計算各主題的內容量（用於難度/出題比例）
weights = {}
for topic in structure.topics:
    weights[topic] = {
        "content_volume": count_chunks(topic),
        "importance": assess_importance(topic),
        "suggested_questions": calculate_question_count(topic)
    }
```

---

## 📊 輸出結構

```json
{
  "scope_id": "scope_20260203_001",
  "description": "藥理學第三章：靜脈麻醉藥",
  "structure": {
    "total_chunks": 234,
    "total_pages": 45,
    "chapters": ["第三章 靜脈麻醉藥"],
    "sections": [
      "3.1 Barbiturates",
      "3.2 Propofol",
      "3.3 Etomidate",
      "3.4 Ketamine"
    ]
  },
  "topic_weights": {
    "Propofol": { "weight": 0.35, "suggested_questions": 7 },
    "Barbiturates": { "weight": 0.25, "suggested_questions": 5 },
    "Ketamine": { "weight": 0.25, "suggested_questions": 5 },
    "Etomidate": { "weight": 0.15, "suggested_questions": 3 }
  },
  "key_concepts": [
    "藥物動力學",
    "劑量計算",
    "副作用",
    "禁忌症"
  ]
}
```

---

## 📝 輸出範例

```
📊 範圍分析完成

🎯 分析範圍: 藥理學第三章 - 靜脈麻醉藥
├── 頁數: 45 頁 (P.89-133)
├── 章節: 4 個 sections
└── 知識點: 12 個核心概念

📈 主題權重分佈
├── Propofol ████████████░░ 35% (建議 7 題)
├── Barbiturates █████████░░░░░ 25% (建議 5 題)
├── Ketamine █████████░░░░░ 25% (建議 5 題)
└── Etomidate ██████░░░░░░░░ 15% (建議 3 題)

🔑 核心概念
├── 藥物動力學 (PK/PD)
├── 劑量計算
├── Context-sensitive half-time
├── 副作用與禁忌症
└── 臨床應用場景
```

````
