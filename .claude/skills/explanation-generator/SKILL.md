````skill
---
name: explanation-generator
description: 詳解生成器，為題目生成詳細解答說明。Triggers: 詳解, 解答, explanation, 生成解答, 解析, 答案說明, 為什麼.
version: 1.0.0
category: output
compatibility:
  - crush
  - claude-code
allowed-tools:
  - source_lookup
  - get_question
  - update_question
---

# 詳解生成器 (Explanation Generator)

## 描述

為題目生成詳細的解答說明，包含：
- 正確答案解釋
- 錯誤選項分析
- 相關知識補充
- 記憶技巧

## 觸發條件

- 「詳解」「解答」「explanation」
- 「生成解答」「解析」
- 「答案說明」

---

## 🔧 生成流程

### Step 1: 載入題目與來源

```python
question = get_question(question_id)

# 取得原始來源內容
source_content = source_lookup(
    document=question.source.document,
    page=question.source.page,
    context_lines=20  # 擴展上下文
)
```

### Step 2: 生成詳解結構

```python
explanation_template = {
    "answer_explanation": "",      # 正確答案解釋
    "incorrect_analysis": {},      # 錯誤選項分析
    "key_concept": "",             # 核心概念
    "clinical_relevance": "",      # 臨床相關性
    "memory_tip": "",              # 記憶技巧
    "related_topics": [],          # 相關主題連結
    "source_citation": ""          # 來源引用
}
```

### Step 3: 生成詳解

```python
prompt = f"""
為以下題目生成詳細解答：

【題目】
{question.stem}

【選項】
{question.options}

【正確答案】
{question.answer}

【來源內容】
{source_content}

【要求】
1. 解釋為什麼正確答案是對的
2. 分析每個錯誤選項為何不對
3. 提供核心概念摘要
4. 如果有臨床相關性，請說明
5. 提供記憶技巧 (如果適用)
"""
```

---

## 📊 詳解結構

```json
{
  "question_id": "q_20260203_001",
  "explanation": {
    "answer": "A",
    "answer_explanation": "Propofol 透過血管擴張和心肌抑制作用而造成低血壓，這是其最常見的心血管副作用。Propofol 會降低全身血管阻力 (SVR) 約 15-25%，同時可能有輕微的心肌抑制作用。",
    
    "incorrect_analysis": {
      "B": "心搏過速 - 錯誤。Propofol 通常不會造成心搏過速，反而可能因為壓力感受器反射被抑制而無法代償性增加心率。",
      "C": "高血壓 - 錯誤。Propofol 是血管擴張劑，會降低而非升高血壓。",
      "D": "心室頻脈 - 錯誤。Propofol 不會造成心室頻脈，相反地它有抗心律不整的特性。"
    },
    
    "key_concept": "Propofol 的心血管效應主要是：\n1. 血管擴張 (主要機制)\n2. 心肌抑制 (較輕微)\n3. 壓力感受器反射抑制",
    
    "clinical_relevance": "在誘導麻醉時，特別是對於低血容量或心功能不佳的病人，需要注意 Propofol 可能造成的低血壓，可能需要預先給予輸液或準備升壓劑。",
    
    "memory_tip": "💡 記憶口訣：「Propofol = 血管鬆 (Vasodilation)」\n諧音：Pro-「鬆」-fol → 血管放鬆 → 低血壓",
    
    "related_topics": [
      "Propofol 藥理學",
      "麻醉誘導劑比較",
      "低血壓處理"
    ],
    
    "source_citation": "Miller's Anesthesia, 9th Ed, P.542, L.15-28"
  }
}
```

---

## 📝 輸出格式

```
📖 詳解

題目: Propofol 最主要的心血管副作用是什麼？

正確答案: A. 低血壓 ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ 為什麼選 A？

Propofol 透過血管擴張和心肌抑制作用造成低血壓，
這是其最常見的心血管副作用。

具體機制：
• 降低全身血管阻力 (SVR) 約 15-25%
• 輕微的心肌抑制作用
• 抑制壓力感受器反射

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ 為什麼其他選項是錯的？

B. 心搏過速
   → Propofol 不會造成心搏過速，反而因壓力
     感受器被抑制而無法代償性增加心率

C. 高血壓
   → Propofol 是血管擴張劑，降低而非升高血壓

D. 心室頻脈
   → Propofol 不造成心室頻脈，反而有
     抗心律不整特性

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 核心概念

Propofol 心血管效應三要素：
1. 血管擴張 (主要)
2. 心肌抑制 (次要)
3. 壓力感受器抑制

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏥 臨床應用

對於低血容量或心功能不佳的病人：
• 預先給予適當輸液
• 準備升壓劑 (如 Ephedrine, Phenylephrine)
• 考慮減少 Propofol 劑量或換用 Etomidate

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 記憶技巧

「Propofol = 血管鬆」
Pro-「鬆」-fol → 血管放鬆 → 低血壓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📚 來源: Miller's Anesthesia, 9th Ed, P.542
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🔄 批次詳解生成

```python
def batch_generate_explanations(questions):
    """批次生成整份試卷的詳解"""
    
    explanations = []
    for q in questions:
        exp = generate_explanation(q)
        explanations.append(exp)
    
    return {
        "exam_id": exam.id,
        "total_questions": len(questions),
        "explanations": explanations
    }
```

````
