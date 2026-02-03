````skill
---
name: exam-assembler
description: 試卷組裝器，將題目組合成完整試卷。Triggers: 組卷, 組裝試卷, assemble, 建立試卷, 試卷組合, 產生試卷.
version: 1.0.0
category: output
compatibility:
  - crush
  - claude-code
allowed-tools:
  - list_questions
  - get_question
  - exam_create
  - exam_save
---

# 試卷組裝器 (Exam Assembler)

## 描述

將生成的題目組合成完整試卷，包含：
- 題目排序與編號
- 難度分布平衡
- 題型混合配置
- 試卷封面與說明

## 觸發條件

- 「組卷」「組裝試卷」
- 「assemble」「建立試卷」
- 「產生試卷」

---

## 🔧 組裝流程

### Step 1: 載入題目池

```python
def load_question_pool(config):
    """載入符合條件的題目"""
    
    questions = list_questions(
        topics=config.topics,
        difficulty=config.difficulty_range,
        types=config.question_types,
        status="validated"  # 只選驗證過的題目
    )
    
    return questions
```

### Step 2: 難度分布配置

```python
def balance_difficulty(questions, config):
    """按難度分布選題"""
    
    distribution = config.difficulty_distribution
    # 預設: {"easy": 0.3, "medium": 0.5, "hard": 0.2}
    
    selected = []
    total = config.total_questions
    
    for difficulty, ratio in distribution.items():
        count = int(total * ratio)
        pool = [q for q in questions if q.difficulty == difficulty]
        selected.extend(random.sample(pool, min(count, len(pool))))
    
    return selected
```

### Step 3: 題型混合

```python
def mix_question_types(questions, config):
    """混合不同題型"""
    
    type_distribution = config.type_distribution
    # 例: {"mcq": 0.7, "essay": 0.2, "question_set": 0.1}
    
    # 確保題型多樣性
    ...
```

### Step 4: 排序與編號

```python
def order_questions(questions, strategy="topic_grouped"):
    """排序題目"""
    
    strategies = {
        "topic_grouped": group_by_topic,         # 按主題分組
        "difficulty_ascending": sort_by_diff,     # 由易到難
        "random": shuffle,                         # 隨機
        "type_grouped": group_by_type             # 按題型分組
    }
    
    ordered = strategies[strategy](questions)
    
    # 加上題號
    for i, q in enumerate(ordered, 1):
        q.number = i
    
    return ordered
```

### Step 5: 生成試卷結構

```python
def assemble_exam(questions, config):
    """組裝最終試卷"""
    
    exam = {
        "metadata": {
            "title": config.title,
            "date": config.date,
            "duration": config.duration,
            "total_questions": len(questions),
            "total_points": sum(q.points for q in questions)
        },
        "instructions": generate_instructions(config),
        "sections": organize_sections(questions, config),
        "answer_key": generate_answer_key(questions),
        "explanations": None  # 可選擇是否包含
    }
    
    return exam
```

---

## 📊 試卷結構

```json
{
  "exam_id": "exam_20260203_001",
  "metadata": {
    "title": "麻醉學模擬考",
    "subtitle": "靜脈麻醉劑專章",
    "date": "2026-02-03",
    "duration_minutes": 60,
    "total_questions": 50,
    "total_points": 100,
    "passing_score": 60
  },
  
  "instructions": {
    "general": "請仔細閱讀每題後選擇最適當的答案",
    "time_management": "建議每題花費 1-2 分鐘",
    "grading": "選擇題每題 2 分，共 100 分"
  },
  
  "sections": [
    {
      "section_id": 1,
      "title": "選擇題",
      "description": "單選題，每題 2 分",
      "questions": [
        {"number": 1, "question_id": "q_001", "points": 2},
        {"number": 2, "question_id": "q_002", "points": 2}
      ]
    },
    {
      "section_id": 2,
      "title": "題組題",
      "description": "閱讀情境後回答問題",
      "questions": [
        {"number": 41, "question_set_id": "qs_001", "points": 10}
      ]
    }
  ],
  
  "statistics": {
    "difficulty_distribution": {
      "easy": 15,
      "medium": 25,
      "hard": 10
    },
    "topic_distribution": {
      "Propofol": 8,
      "Etomidate": 5,
      "Ketamine": 5
    }
  }
}
```

---

## 📝 輸出格式

```
📋 試卷組裝完成

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 麻醉學模擬考 - 靜脈麻醉劑專章
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 試卷摘要

題數: 50 題
總分: 100 分
時間: 60 分鐘
及格: 60 分

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 難度分布

Easy   ████████████░░░░░░░░ 30% (15題)
Medium ████████████████████ 50% (25題)
Hard   ████████░░░░░░░░░░░░ 20% (10題)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📑 試卷結構

第一部分: 選擇題 (1-40題, 80分)
├── 單選題 40 題 × 2 分

第二部分: 題組題 (41-50題, 20分)
├── 題組 1: 術中低血壓處理 (5題, 10分)
└── 題組 2: 藥物交互作用 (5題, 10分)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📚 主題涵蓋

Propofol .............. 8 題 (16%)
Etomidate ............. 5 題 (10%)
Ketamine .............. 5 題 (10%)
Barbiturates .......... 4 題 (8%)
Benzodiazepines ....... 6 題 (12%)
藥物動力學 ............ 8 題 (16%)
臨床應用 .............. 14題 (28%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ 組裝完成！

可用操作:
• 匯出 PDF: `export pdf exam_20260203_001`
• 匯出 Word: `export docx exam_20260203_001`
• 線上作答: `publish exam_20260203_001`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## ⚙️ 配置選項

```python
exam_config = {
    "title": "麻醉學模擬考",
    "total_questions": 50,
    "duration_minutes": 60,
    
    # 難度分布
    "difficulty_distribution": {
        "easy": 0.3,
        "medium": 0.5,
        "hard": 0.2
    },
    
    # 題型分布
    "type_distribution": {
        "single_choice": 0.7,
        "multiple_choice": 0.1,
        "question_set": 0.2
    },
    
    # 題目排序
    "ordering_strategy": "difficulty_ascending",
    
    # 是否包含解答
    "include_answers": False,
    "include_explanations": False
}
```

````
