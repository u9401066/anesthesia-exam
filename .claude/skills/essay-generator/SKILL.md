---
name: essay-generator
description: 問答題/申論題生成器，支援簡答、解釋、比較、分析等題型。Triggers: 問答題, 申論題, 簡答題, essay, short answer, 解釋題, 比較題, 分析題.
version: 1.0.0
category: question-generation
compatibility:
  - crush
  - claude-code
allowed-tools:
  - asset-aware__get_section_content
  - asset-aware__search_source_location
  - exam-generator__exam_save_question
---

# 問答題生成器 (Essay Generator)

## 描述

專門生成問答題/申論題，支援：
- 簡答題 (定義、列舉)
- 解釋題 (機制、原理)
- 比較題 (異同分析)
- 案例分析題 (臨床情境)

## 觸發條件

- 「問答題」「申論題」「簡答題」
- 「essay」「short answer」
- 「解釋題」「比較題」

---

## 🔧 生成流程

### Step 1: 決定問答類型

```python
essay_types = {
    "definition": "請定義/說明...",       # 定義型
    "explanation": "請解釋...的機制",     # 解釋型
    "comparison": "請比較...與...的異同", # 比較型
    "case_analysis": "根據以下情境...",   # 案例型
    "enumeration": "請列舉...",           # 列舉型
    "application": "如何應用...於..."     # 應用型
}
```

### Step 2: 查詢相關內容

```python
contexts = asset-aware__get_section_content(
    query=topic,
    scope=scope,
    top_k=10  # 問答題需要更多上下文
)
```

### Step 3: 生成題目與評分標準

```python
prompt = f"""
根據以下教材內容生成一道{essay_type}問答題：

【教材內容】
{contexts}

【要求】
- 類型: {essay_type}
- 難度: {difficulty}
- 預期作答長度: {expected_length}

【輸出格式】
{{
  "question": "題目內容",
  "type": "{essay_type}",
  "expected_points": ["要點1", "要點2", "要點3"],
  "scoring_rubric": {{
    "full_marks": 10,
    "criteria": [
      {{"point": "提及核心概念", "score": 3}},
      {{"point": "解釋正確", "score": 4}},
      {{"point": "舉例適當", "score": 3}}
    ]
  }},
  "sample_answer": "參考答案...",
  "source": [
    {{"page": 42, "lines": "15-20", "text": "..."}},
    {{"page": 45, "lines": "5-10", "text": "..."}}
  ]
}}
"""
```

---

## 📊 題型範例

### 定義型 (Definition)

```json
{
  "type": "definition",
  "question": "請說明什麼是 Minimum Alveolar Concentration (MAC)，並列舉影響 MAC 的因素。",
  "expected_points": [
    "MAC 的定義",
    "1 MAC 的臨床意義",
    "影響因素（年齡、溫度、藥物等）"
  ],
  "scoring_rubric": {
    "full_marks": 10,
    "criteria": [
      {"point": "正確定義 MAC", "score": 3},
      {"point": "說明 1 MAC 意義", "score": 2},
      {"point": "列出 3+ 影響因素", "score": 3},
      {"point": "解釋影響機制", "score": 2}
    ]
  }
}
```

### 比較型 (Comparison)

```json
{
  "type": "comparison",
  "question": "請比較 Propofol 與 Etomidate 在麻醉誘導時的優缺點。",
  "expected_points": [
    "起效速度比較",
    "心血管穩定性比較",
    "腎上腺抑制作用",
    "適用情境差異"
  ],
  "scoring_rubric": {
    "full_marks": 15,
    "criteria": [
      {"point": "Propofol 特性完整", "score": 4},
      {"point": "Etomidate 特性完整", "score": 4},
      {"point": "比較有條理", "score": 4},
      {"point": "臨床選擇建議", "score": 3}
    ]
  }
}
```

### 案例分析型 (Case Analysis)

```json
{
  "type": "case_analysis",
  "question": "一位 65 歲男性，有冠狀動脈疾病病史，需要進行急診腹部手術。請說明麻醉誘導藥物的選擇考量。",
  "expected_points": [
    "病人評估重點",
    "藥物選擇理由",
    "劑量調整考量",
    "監測重點"
  ],
  "context": {
    "patient": "65歲男性",
    "history": "冠狀動脈疾病",
    "procedure": "急診腹部手術"
  }
}
```

---

## 📝 輸出格式

```
📝 問答題生成完成

題目 #1 [比較題] [Hard] ━━━━━━━━━━━━━━━━━━━━━

請比較 Succinylcholine 與 Rocuronium 作為
快速誘導插管肌肉鬆弛劑的優缺點，並說明
各自的適應症和禁忌症。(15分)

📊 評分標準:
├── Succinylcholine 特性 (4分)
├── Rocuronium 特性 (4分)
├── 比較分析 (4分)
└── 臨床選擇建議 (3分)

📚 來源:
├── Miller's Anesthesia P.523-528
└── Miller's Anesthesia P.534-540

💡 參考答案要點:
├── 起效速度: Sux 45-60s vs Roc 60-90s
├── 作用時間: Sux 5-10min vs Roc 30-45min
├── Sux 禁忌: 高血鉀風險、惡性高熱
└── Sugammadex 可逆轉 Rocuronium
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

