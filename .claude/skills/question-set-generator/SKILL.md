````skill
---
name: question-set-generator
description: 題組題生成器，建立共用情境的關聯題目組。Triggers: 題組, 題組題, question set, 情境題, 病例題, 連續題.
version: 1.0.0
category: question-generation
compatibility:
  - crush
  - claude-code
allowed-tools:
  - source_lookup
  - source_cite
  - exam_save_question
---

# 題組題生成器 (Question Set Generator)

## 描述

生成共用情境的題組，通常包含：
- 一個共用情境/病例描述
- 3-5 道相關聯的子題目
- 題目間有邏輯遞進關係

非常適合醫學考試的臨床情境題。

## 觸發條件

- 「題組」「題組題」
- 「情境題」「病例題」
- 「question set」

---

## 🔧 生成流程

### Step 1: 選擇情境類型

```python
scenarios = {
    "clinical_case": "臨床病例",     # 完整病人故事
    "lab_scenario": "實驗室情境",   # 檢驗數據解讀
    "procedure": "手術情境",         # 手術中問題
    "emergency": "緊急狀況",         # 緊急處理
    "drug_interaction": "藥物交互"   # 藥物問題
}
```

### Step 2: 建立情境描述

```python
prompt = f"""
請建立一個{scenario_type}的臨床情境，需要涵蓋以下主題：
{topics}

【情境要求】
- 真實性: 符合臨床實務
- 完整性: 提供足夠的資訊
- 延展性: 可以衍生出 {num_questions} 道題目

【病人資訊】
- 基本資料（年齡、性別）
- 主訴
- 病史
- 檢查/檢驗結果
- 目前狀況
"""
```

### Step 3: 生成子題目

```python
# 子題目需要有邏輯遞進
question_progression = [
    "診斷/評估類",       # 第一題：判斷問題
    "機制/原因類",       # 第二題：解釋原因
    "處置/治療類",       # 第三題：如何處理
    "預後/預防類"        # 第四題：後續追蹤
]
```

---

## 📊 題組結構

```json
{
  "type": "question_set",
  "set_id": "qs_20260203_001",
  "scenario": {
    "title": "術中低血壓處理",
    "context": "一位 68 歲女性，ASA III，接受全髖關節置換術...",
    "patient": {
      "age": 68,
      "gender": "F",
      "asa": "III",
      "history": ["高血壓", "糖尿病", "冠心症"],
      "current_meds": ["Metoprolol", "Metformin"]
    },
    "situation": "麻醉誘導後血壓從 140/85 降至 75/45 mmHg..."
  },
  "questions": [
    {
      "sub_id": 1,
      "type": "single_choice",
      "question": "最可能的低血壓原因是？",
      "options": ["A. 出血", "B. 藥物作用", "C. 過敏反應", "D. 心肌梗塞"],
      "answer": "B",
      "points": 2
    },
    {
      "sub_id": 2,
      "type": "single_choice",
      "question": "首要處置應該是？",
      "options": ["A. 給予升壓劑", "B. 大量輸液", "C. 檢查出血", "D. 停止手術"],
      "answer": "A",
      "points": 2
    },
    {
      "sub_id": 3,
      "type": "short_answer",
      "question": "請說明 Propofol 造成低血壓的機制。",
      "expected_points": ["血管擴張", "心肌抑制", "交感神經抑制"],
      "points": 3
    }
  ],
  "total_points": 7,
  "source": [
    {"page": 542, "topic": "Propofol 心血管效應"},
    {"page": 1823, "topic": "術中低血壓處理"}
  ]
}
```

---

## 📝 輸出格式

```
📝 題組生成完成

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 題組: 術中低血壓處理 (共 7 分)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【情境描述】
一位 68 歲女性，ASA III，有高血壓、糖尿病、
冠心症病史，目前服用 Metoprolol 和 Metformin。
今日接受全髖關節置換術，使用 Propofol 2mg/kg
進行麻醉誘導。

誘導後血壓從 140/85 mmHg 降至 75/45 mmHg，
心率從 72 降至 58 bpm。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

第 1 題 [選擇題] (2分)
最可能的低血壓原因是？
A. 術中出血
B. 藥物作用 ✓
C. 過敏反應
D. 急性心肌梗塞

第 2 題 [選擇題] (2分)
此時首要處置應該是？
A. 給予升壓劑 ✓
B. 大量輸液
C. 檢查是否有隱藏出血
D. 停止手術

第 3 題 [簡答題] (3分)
請說明 Propofol 造成低血壓的機制。

📚 來源:
├── Miller's P.542 (Propofol 心血管效應)
└── Miller's P.1823 (術中低血壓處理)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🎯 題目遞進設計

```
┌─────────────────────────────────────────┐
│              共用情境                    │
│         (病例/狀況描述)                  │
└────────────────┬────────────────────────┘
                 │
    ┌────────────┼────────────┬────────────┐
    ▼            ▼            ▼            ▼
┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│ 第1題  │  │ 第2題  │  │ 第3題  │  │ 第4題  │
│ 診斷   │→ │ 機制   │→ │ 處置   │→ │ 預後   │
│ 判斷   │  │ 解釋   │  │ 治療   │  │ 預防   │
└────────┘  └────────┘  └────────┘  └────────┘
   Easy      Medium      Medium       Hard
```

````
