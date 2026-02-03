````skill
---
name: duplicate-checker
description: 重複題目檢查器，檢測語意重複和過度相似的題目。Triggers: 查重, 重複檢查, duplicate, 相似題, 題目查重, 檢查重複.
version: 1.0.0
category: quality-control
compatibility:
  - crush
  - claude-code
allowed-tools:
  - semantic_search
  - list_questions
  - get_question
---

# 重複題目檢查器 (Duplicate Checker)

## 描述

檢測題目庫中語意重複或過度相似的題目，避免：
- 完全相同的題目
- 僅改寫但考點相同的題目
- 過於相似的選項組合

## 觸發條件

- 「查重」「重複檢查」
- 「duplicate」「相似題」
- 「題目查重」

---

## 🔧 檢查流程

### Step 1: 語意相似度計算

```python
def check_duplicate(new_question, threshold=0.85):
    # 取得所有現有題目
    existing = list_questions(status="all")
    
    duplicates = []
    for q in existing:
        similarity = semantic_similarity(
            new_question.stem,
            q.stem
        )
        
        if similarity > threshold:
            duplicates.append({
                "question_id": q.id,
                "similarity": similarity,
                "type": classify_duplicate_type(similarity)
            })
    
    return duplicates
```

### Step 2: 分類重複類型

```python
def classify_duplicate_type(similarity):
    if similarity > 0.98:
        return "EXACT"      # 完全相同
    elif similarity > 0.90:
        return "NEAR_EXACT" # 幾乎相同
    elif similarity > 0.85:
        return "SIMILAR"    # 高度相似
    elif similarity > 0.75:
        return "RELATED"    # 相關題目
    else:
        return "UNIQUE"     # 獨特題目
```

### Step 3: 考點重複檢查

```python
def check_concept_overlap(new_q, existing):
    """即使題目不同，考點可能相同"""
    new_concepts = extract_concepts(new_q)
    
    for q in existing:
        existing_concepts = extract_concepts(q)
        overlap = jaccard_similarity(new_concepts, existing_concepts)
        
        if overlap > 0.8:
            return {
                "overlapping_concepts": new_concepts & existing_concepts,
                "suggestion": "考點高度重疊，建議刪除或修改"
            }
```

---

## 📊 重複類型

| 類型 | 相似度 | 處理方式 |
| ---- | ------ | -------- |
| EXACT | >98% | 🚫 拒絕，刪除重複 |
| NEAR_EXACT | 90-98% | ⚠️ 警告，需要人工審核 |
| SIMILAR | 85-90% | ⚠️ 提示，考慮合併或分化 |
| RELATED | 75-85% | ℹ️ 資訊，標記為相關題組 |
| UNIQUE | <75% | ✅ 通過，可以加入 |

---

## 📝 輸出格式

```
🔍 重複檢查報告

新題目: "Propofol 的主要心血管副作用是?"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 相似度分析:

#1 [NEAR_EXACT] 92.3% ⚠️
├── ID: q_20260201_005
├── 題目: "Propofol 最常見的心血管不良反應?"
└── 建議: 考慮合併或選擇其一

#2 [SIMILAR] 87.1% ⚠️
├── ID: q_20260201_012
├── 題目: "使用 Propofol 誘導時需注意哪些心血管變化?"
└── 建議: 兩題考點略有不同，可保留

#3 [RELATED] 78.4% ℹ️
├── ID: q_20260202_003
├── 題目: "比較 Propofol 與 Etomidate 的心血管效應"
└── 建議: 考點相關但不同，無需處理

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 考點重疊分析:
├── 共同考點: Propofol, 心血管, 副作用
├── 重疊度: 85%
└── 建議: 新題目可加入，但建議放入同一題組

✅ 結論: 可加入題庫，但需標記與 #1 相關
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🔄 批次查重

```python
def batch_duplicate_check(questions):
    """批次檢查整份試卷的內部重複"""
    
    pairs = []
    for i, q1 in enumerate(questions):
        for j, q2 in enumerate(questions[i+1:], i+1):
            sim = semantic_similarity(q1.stem, q2.stem)
            if sim > 0.75:
                pairs.append((i+1, j+1, sim))
    
    return pairs
```

輸出範例：
```
📋 試卷內部查重

發現 2 組相似題目:

#3 ↔ #15 (88.2%)
├── 第3題: "Succinylcholine 的作用時間?"
├── 第15題: "Succinylcholine 作用持續多久?"
└── 建議: 刪除其中一題

#7 ↔ #22 (76.4%)
├── 第7題: "解釋 MAC 的定義"
├── 第22題: "什麼是 Minimum Alveolar Concentration?"
└── 建議: 保留但調整方向
```

````
