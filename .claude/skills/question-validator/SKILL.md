````skill
---
name: question-validator
description: 題目驗證器，檢查題目品質、正確性、來源依據。Triggers: 驗證題目, 檢查題目, validate, 品質檢查, QA, 審核題目, check question.
version: 1.0.0
category: quality-control
compatibility:
  - crush
  - claude-code
allowed-tools:
  - source_lookup
  - source_verify
  - get_question
---

# 題目驗證器 (Question Validator)

## 描述

驗證生成題目的品質，包含：
- 事實正確性（對照來源）
- 選項合理性（無明顯錯誤/陷阱）
- 語法清晰度
- 來源可追溯性

## 觸發條件

- 「驗證題目」「檢查題目」
- 「validate」「品質檢查」
- 「QA」「審核題目」

---

## 🔧 驗證流程

### Step 1: 載入題目

```python
question = get_question(question_id)
```

### Step 2: 事實驗證

```python
# 對照原始來源
source_text = source_lookup(
    document=question.source.document,
    page=question.source.page,
    lines=question.source.lines
)

# 比對答案是否與來源一致
fact_check = verify_fact(
    claim=question.answer,
    source=source_text
)
```

### Step 3: 選項驗證 (MCQ)

```python
# 檢查選項問題
option_issues = []

# 1. 檢查是否有多個正確答案
for option in question.options:
    if is_technically_correct(option, source_text):
        option_issues.append(f"{option} 可能也是正確的")

# 2. 檢查明顯錯誤的陷阱
for option in question.distractors:
    if is_obviously_wrong(option):
        option_issues.append(f"{option} 太明顯錯誤")

# 3. 檢查選項是否有重疊
if has_overlapping_options(question.options):
    option_issues.append("選項間有重疊")
```

### Step 4: 語法檢查

```python
# 檢查語法問題
grammar_issues = check_grammar([
    question.stem,
    *question.options
])

# 檢查是否有歧義
ambiguity = check_ambiguity(question.stem)
```

### Step 5: 來源追蹤驗證

```python
# 確認來源存在且可追溯
source_valid = source_verify(
    document=question.source.document,
    page=question.source.page,
    text=question.source.original_text
)
```

---

## 📊 驗證報告

```json
{
  "question_id": "q_20260203_001",
  "validation_result": "PASS",
  "score": 92,
  "checks": {
    "fact_accuracy": {
      "status": "PASS",
      "score": 100,
      "detail": "答案與來源一致"
    },
    "option_quality": {
      "status": "WARNING",
      "score": 85,
      "issues": ["選項 C 可能太明顯錯誤"]
    },
    "grammar": {
      "status": "PASS",
      "score": 95,
      "issues": []
    },
    "source_traceability": {
      "status": "PASS",
      "score": 100,
      "verified": true
    },
    "ambiguity": {
      "status": "PASS",
      "score": 88,
      "detail": "題目描述清晰"
    }
  },
  "recommendations": [
    "建議修改選項 C 使其更具迷惑性"
  ]
}
```

---

## 📝 輸出格式

```
✅ 題目驗證報告

題目: q_20260203_001
總分: 92/100 | 結果: PASS ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
檢查項目              狀態      分數
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
事實正確性            ✓ PASS    100
選項品質              ⚠ WARN     85
語法清晰度            ✓ PASS     95
來源可追溯            ✓ PASS    100
無歧義性              ✓ PASS     88
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ 警告:
└── 選項 C「血壓升高」可能太明顯錯誤

💡 建議:
└── 修改選項 C 為更具迷惑性的選項，
    如「心搏過速」
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🚫 自動拒絕條件

以下情況會自動標記為 FAIL：

1. **答案與來源矛盾** - 事實錯誤
2. **多個選項都正確** - 選擇題無效
3. **所有選項都錯誤** - 題目無解
4. **來源無法驗證** - 不可追溯
5. **題目有歧義** - 可能有多種解讀

````
