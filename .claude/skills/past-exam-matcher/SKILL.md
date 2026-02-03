````skill
---
name: past-exam-matcher
description: 考古題比對器，比對新題目與歷屆考題的相似度。Triggers: 考古題比對, 比對考古題, 歷屆比對, match past, 類似考古題, 考過沒.
version: 1.0.0
category: past-exam
compatibility:
  - crush
  - claude-code
allowed-tools:
  - semantic_search
  - list_past_exams
  - get_past_exam_question
---

# 考古題比對器 (Past Exam Matcher)

## 描述

比對新生成的題目與歷屆考題的相似度，用於：
- 避免出到一模一樣的考古題
- 找出相似題型作為參考
- 驗證題目品質（是否達到考試標準）

## 觸發條件

- 「考古題比對」「比對考古題」
- 「match past」「類似考古題」
- 「這題考過沒」

---

## 🔧 比對流程

### Step 1: 語意搜尋

```python
def find_similar_past_questions(new_question, top_k=10):
    """搜尋相似的考古題"""
    
    # 使用語意搜尋
    results = semantic_search(
        query=new_question.stem,
        index="past_exams",
        top_k=top_k
    )
    
    return results
```

### Step 2: 相似度評分

```python
def calculate_similarity(new_q, past_q):
    """計算綜合相似度"""
    
    # 題幹相似度
    stem_sim = semantic_similarity(new_q.stem, past_q.stem)
    
    # 選項相似度 (如果都是選擇題)
    if new_q.type == "mcq" and past_q.type == "mcq":
        options_sim = options_similarity(new_q.options, past_q.options)
    else:
        options_sim = None
    
    # 考點相似度
    concept_sim = concept_overlap(new_q.concepts, past_q.concepts)
    
    # 綜合評分
    overall = weighted_average([
        (stem_sim, 0.5),
        (options_sim, 0.2) if options_sim else (0, 0),
        (concept_sim, 0.3)
    ])
    
    return {
        "overall": overall,
        "stem": stem_sim,
        "options": options_sim,
        "concepts": concept_sim
    }
```

### Step 3: 分類匹配結果

```python
def classify_match(similarity):
    """分類匹配結果"""
    
    if similarity.overall > 0.95:
        return "IDENTICAL"      # 幾乎相同
    elif similarity.overall > 0.85:
        return "NEAR_DUPLICATE" # 高度相似
    elif similarity.overall > 0.70:
        return "SIMILAR"        # 相似變體
    elif similarity.overall > 0.50:
        return "RELATED"        # 相關題目
    else:
        return "UNIQUE"         # 獨特新題
```

---

## 📊 比對報告

```json
{
  "new_question_id": "q_20260203_001",
  "query": "Propofol 最主要的心血管副作用是什麼？",
  
  "matches": [
    {
      "exam": "2024 麻醉專科考試",
      "question_id": "2024_Q45",
      "stem": "Propofol 誘導時最常見的心血管反應是？",
      "similarity": {
        "overall": 0.89,
        "stem": 0.92,
        "options": 0.85,
        "concepts": 0.88
      },
      "classification": "NEAR_DUPLICATE",
      "verdict": "⚠️ 高度相似，建議修改"
    },
    {
      "exam": "2022 麻醉專科考試",
      "question_id": "2022_Q23",
      "stem": "關於 Propofol 的敘述，下列何者正確？",
      "similarity": {
        "overall": 0.64,
        "stem": 0.58,
        "options": 0.70,
        "concepts": 0.72
      },
      "classification": "RELATED",
      "verdict": "✅ 相關但不同，可參考"
    }
  ],
  
  "recommendation": "建議改寫題幹或調整選項以避免過度相似"
}
```

---

## 📝 輸出格式

```
🔍 考古題比對報告

新題目: "Propofol 最主要的心血管副作用是什麼？"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 最相似的考古題

#1 [NEAR_DUPLICATE] 89% ⚠️
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 2024 麻醉專科考試 - 第 45 題
📝 Propofol 誘導時最常見的心血管反應是？
   A. 低血壓 ✓
   B. 心搏過速
   C. 高血壓
   D. 心律不整

相似度分析:
├── 題幹: 92%
├── 選項: 85%
└── 考點: 88%

⚠️ 結論: 高度相似，建議修改後使用
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#2 [SIMILAR] 72%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 2023 麻醉專科考試 - 第 31 題
📝 下列哪種靜脈麻醉劑最可能造成低血壓？
   A. Propofol ✓
   B. Etomidate
   C. Ketamine
   D. Midazolam

相似度分析:
├── 題幹: 68%
├── 選項: 78%
└── 考點: 70%

✅ 結論: 相似變體，可作為參考
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#3 [RELATED] 58% ℹ️
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 2022 麻醉專科考試 - 第 23 題
📝 關於 Propofol 的敘述，下列何者正確？
   ...

✅ 結論: 相關題目，無重複問題
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 統計摘要

比對範圍: 2020-2025 考古題 (共 600 題)
相似題數: 3 題
├── NEAR_DUPLICATE: 1
├── SIMILAR: 1
└── RELATED: 1

💡 建議:
由於與 2024 年第 45 題高度相似，建議：
1. 調整問法: "造成 Propofol 低血壓的機制是？"
2. 或改為比較題: "比較 Propofol 與 Etomidate 的心血管效應"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🔄 批次比對

```python
def batch_match(questions, threshold=0.85):
    """批次比對整份試卷"""
    
    results = []
    for q in questions:
        matches = find_similar_past_questions(q)
        high_similarity = [m for m in matches if m.similarity > threshold]
        
        if high_similarity:
            results.append({
                "question": q,
                "matches": high_similarity,
                "action_needed": True
            })
    
    return results
```

輸出：
```
📋 批次考古題比對

試卷: 2026 模擬考 (50題)
比對範圍: 2020-2025 考古題

⚠️ 需要處理: 5 題

#12 ↔ 2024-Q45 (89%) - 建議修改
#23 ↔ 2023-Q18 (91%) - 建議修改
#31 ↔ 2022-Q67 (86%) - 建議修改
#45 ↔ 2024-Q12 (88%) - 建議修改
#48 ↔ 2021-Q55 (95%) - 強烈建議替換

✅ 通過: 45 題 (無高度相似)
```

````
