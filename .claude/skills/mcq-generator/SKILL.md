````skill
---
name: mcq-generator
description: 選擇題生成器，支援單選、多選、複合選項等格式，參考 Ragas 難度分類。Triggers: 選擇題, 單選題, 多選題, MCQ, multiple choice, 四選一, 五選一, 選項題.
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

# 選擇題生成器 (MCQ Generator)

## 描述

專門生成選擇題（Multiple Choice Questions），支援：
- 單選題 (4選1, 5選1)
- 多選題 (選出所有正確答案)
- 複合選項 (如 ab, cde, 以上皆是)

參考 Ragas 的難度分類：Simple, Reasoning, Multi-Context

## 觸發條件

- 「選擇題」「單選題」「多選題」
- 「MCQ」「multiple choice」
- 「四選一」「五選一」

---

## 🔧 生成流程

### Step 1: 查詢相關內容

```python
# 從索引中查詢相關教材內容
contexts = source_lookup(
    query=topic,
    scope=scope,
    top_k=5
)
```

### Step 2: 決定複雜度

```python
# 根據難度配置決定問題類型
complexity_map = {
    "easy": "single_hop_specific",    # 單一事實
    "medium": "single_hop_abstract",  # 需要理解
    "hard": "multi_hop_reasoning"     # 多來源推理
}
```

### Step 3: 生成題目

```python
prompt = f"""
根據以下教材內容生成一道{difficulty}難度的選擇題：

【教材內容】
{contexts}

【要求】
- 題型: {options_count}選1
- 難度: {difficulty}
- 複雜度: {complexity}
- 必須有明確來源依據

【輸出格式】
{{
  "question": "題目內容",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "answer": "A",
  "distractor_rationale": {{
    "B": "為何 B 是錯誤的",
    "C": "為何 C 是錯誤的",
    "D": "為何 D 是錯誤的"
  }},
  "source": {{
    "page": 42,
    "lines": "15-20",
    "original_text": "..."
  }}
}}
"""
```

### Step 4: 驗證與儲存

```python
# 驗證選項不重複、答案正確
validate_mcq(question)
# 儲存
exam_save_question(question)
```

---

## 📊 題目類型

### 單選題 (Single Choice)

```json
{
  "type": "single_choice",
  "question": "Propofol 最常見的副作用是？",
  "options": [
    "A. 低血壓",
    "B. 心搏過速",
    "C. 高血壓",
    "D. 心室頻脈"
  ],
  "answer": "A",
  "difficulty": "easy"
}
```

### 多選題 (Multiple Choice)

```json
{
  "type": "multiple_choice",
  "question": "下列哪些是 Propofol 的特性？(選出所有正確答案)",
  "options": [
    "A. 水溶性",
    "B. 快速起效",
    "C. 無痛注射",
    "D. 快速恢復",
    "E. 具有抗嘔吐作用"
  ],
  "answer": ["B", "D", "E"],
  "difficulty": "medium"
}
```

### 複合選項題

```json
{
  "type": "compound_choice",
  "question": "關於 Propofol 的敘述，正確的是？",
  "options": [
    "A. 快速起效",
    "B. 具有鎮痛作用",
    "C. 可能造成低血壓",
    "D. AC",
    "E. ABC"
  ],
  "answer": "D",
  "difficulty": "hard"
}
```

---

## 📈 難度控制

| 難度 | 複雜度 | 特徵 |
| ---- | ------ | ---- |
| Easy | Single-hop Specific | 單一事實記憶，答案明確 |
| Medium | Single-hop Abstract | 需要理解概念，可能有陷阱選項 |
| Hard | Multi-hop Reasoning | 需要連結多個概念，推理得出答案 |

---

## 📝 輸出格式

```
📝 選擇題生成完成

題目 #1 [Medium] ━━━━━━━━━━━━━━━━━━━━━━━━━━
Propofol 的 context-sensitive half-time 特性意味著：

A. 輸注時間越長，藥效越強
B. 輸注時間越長，恢復時間不會顯著延長 ✓
C. 輸注時間與恢復時間成正比
D. 與其他藥物無關

📚 來源: Miller's Anesthesia, P.542, L.12-18
💡 說明: Context-sensitive half-time 較短表示...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

````
