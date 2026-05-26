---
name: difficulty-classifier
description: 難度分類器，基於 Ragas 標準評估題目難度。Triggers: 難度分類, 難度評估, difficulty, 評估難度, 調整難度.
version: 1.0.0
category: quality-control
compatibility:
  - crush
  - claude-code
allowed-tools:
  - get_question
  - update_question
---

# 難度分類器 (Difficulty Classifier)

## 描述

基於 Ragas 論文的難度分類標準，評估題目難度：
- Single-hop Specific (簡單)
- Single-hop Abstract (中等)
- Multi-hop Reasoning (困難)

## 觸發條件

- 「難度分類」「難度評估」
- 「difficulty」「評估難度」
- 「調整難度」

---

## 🔧 分類流程

### Step 1: 分析題目結構

```python
question = get_question(question_id)

# 分析題目特徵
features = analyze_question_features(question)
# - required_facts: 需要的事實數量
# - reasoning_steps: 推理步驟數
# - abstraction_level: 抽象程度
# - context_dependency: 情境依賴度
```

### Step 2: 計算難度指標

```python
# Ragas 風格的難度評估
metrics = {
    "hop_count": count_reasoning_hops(question),
    "specificity": measure_specificity(question),
    "cognitive_level": bloom_taxonomy_level(question),
    "distractor_quality": rate_distractors(question)
}
```

### Step 3: 分類

```python
def classify_difficulty(metrics):
    if metrics.hop_count == 1 and metrics.specificity > 0.8:
        return "easy", "single_hop_specific"
    elif metrics.hop_count == 1 and metrics.specificity <= 0.8:
        return "medium", "single_hop_abstract"
    elif metrics.hop_count >= 2:
        return "hard", "multi_hop_reasoning"
```

---

## 📊 難度分類標準

### Easy: Single-hop Specific

```
特徵:
- 直接從來源找到答案
- 不需要額外推理
- 答案是明確的事實

範例:
Q: Propofol 的誘導劑量是多少？
A: 1.5-2.5 mg/kg

評估:
- hop_count: 1
- specificity: 0.95 (非常具體)
- cognitive_level: Remember
```

### Medium: Single-hop Abstract

```
特徵:
- 需要理解概念
- 可能需要轉換或解釋
- 答案需要一定理解力

範例:
Q: 為什麼 Propofol 會造成低血壓？
A: 血管擴張 + 心肌抑制

評估:
- hop_count: 1
- specificity: 0.6 (需要理解機制)
- cognitive_level: Understand
```

### Hard: Multi-hop Reasoning

```
特徵:
- 需要連結多個概念
- 需要多步推理
- 可能需要整合多個來源

範例:
Q: 一位有 COPD 的病人在使用 Propofol 誘導後
   血壓下降，心率卻沒有代償性增加，最可能
   的原因是什麼？
A: Propofol 抑制壓力感受器反射

評估:
- hop_count: 3 (COPD特性 + Propofol效應 + 反射弧)
- specificity: 0.4 (需要綜合分析)
- cognitive_level: Analyze
```

---

## 📈 Bloom's Taxonomy 對照

| 難度 | Cognitive Level | 動詞 |
| ---- | --------------- | ---- |
| Easy | Remember | 列出、說出、定義 |
| Easy-Med | Understand | 解釋、描述、比較 |
| Medium | Apply | 應用、計算、示範 |
| Med-Hard | Analyze | 分析、區分、推論 |
| Hard | Evaluate | 評估、判斷、辯護 |
| Hard | Create | 設計、規劃、組合 |

---

## 📝 輸出格式

```
📊 難度分類報告

題目: q_20260203_001
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

難度評估: MEDIUM (Single-hop Abstract)

指標分析:
├── Hop Count:       1
├── Specificity:     0.62
├── Cognitive Level: Understand
├── Distractor:      Good (0.78)
└── Context Need:    Low

📈 難度分布圖:
Easy    ████████░░░░░░░░░░░░ 38%
Medium  ████████████░░░░░░░░ 58% ← 當前
Hard    ████░░░░░░░░░░░░░░░░ 4%

💡 調整建議:
若要提高難度至 Hard，可以：
├── 加入臨床情境
├── 要求整合多個概念
└── 增加推理步驟
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🎯 難度調整建議

```python
def suggest_difficulty_change(question, target_difficulty):
    current = question.difficulty
    
    if current < target_difficulty:
        # 提高難度
        return [
            "加入臨床情境",
            "改為多來源整合",
            "增加干擾選項的迷惑性",
            "要求解釋而非記憶"
        ]
    else:
        # 降低難度
        return [
            "簡化問題描述",
            "減少情境細節",
            "讓正確答案更明確",
            "減少需要的推理步驟"
        ]
```

