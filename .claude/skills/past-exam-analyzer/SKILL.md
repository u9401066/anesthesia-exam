---
name: past-exam-analyzer
description: 考古題分析器，分析歷屆考題的出題模式和重點分布。Triggers: 考古題分析, 歷屆考題, past exam, 考古題, 歷屆, 出題模式, 考題分析.
version: 1.0.0
category: past-exam
compatibility:
  - crush
  - claude-code
allowed-tools:
  - exam-generator__exam_get_past_exam
  - exam-generator__exam_get_past_exam
  - exam-generator__exam_build_past_exam_blueprint
---

# 考古題分析器 (Past Exam Analyzer)

## 描述

分析歷屆考題，識別：
- 出題模式（哪些主題常考）
- 重點分布（章節權重）
- 難度趨勢（歷年難度變化）
- 題型偏好（選擇/問答比例）

這對於預測考試重點和設計模擬考非常有用。

## 觸發條件

- 「考古題分析」「歷屆考題」
- 「past exam」「考古題」
- 「出題模式」

---

## 🔧 分析流程

### Step 1: 載入考古題

```python
def load_past_exams(years=5):
    """載入近 N 年的考古題"""
    exams = exam-generator__exam_get_past_exam(
        exam_type="board",  # 專科考試
        years=years
    )
    return exams
```

### Step 2: 主題分布分析

```python
def analyze_topic_distribution(exams):
    """分析各主題的出題頻率"""
    
    topic_counts = defaultdict(int)
    
    for exam in exams:
        for question in exam.questions:
            for topic in question.topics:
                topic_counts[topic] += 1
    
    # 計算比例
    total = sum(topic_counts.values())
    distribution = {
        topic: count / total 
        for topic, count in topic_counts.items()
    }
    
    return sorted(distribution.items(), key=lambda x: -x[1])
```

### Step 3: 重要性評分

```python
def calculate_importance_score(topic, exams):
    """計算主題重要性分數"""
    
    # 因素權重
    frequency_weight = 0.4      # 出現頻率
    recency_weight = 0.3        # 近期是否出現
    consistency_weight = 0.2    # 是否每年都考
    difficulty_weight = 0.1     # 平均難度
    
    freq = topic_frequency(topic, exams)
    recency = topic_recency(topic, exams)
    consistency = topic_consistency(topic, exams)
    difficulty = topic_avg_difficulty(topic, exams)
    
    score = (
        freq * frequency_weight +
        recency * recency_weight +
        consistency * consistency_weight +
        difficulty * difficulty_weight
    )
    
    return score
```

### Step 4: 趨勢分析

```python
def analyze_trends(exams):
    """分析出題趨勢"""
    
    yearly_data = group_by_year(exams)
    
    trends = {
        "rising_topics": [],      # 出題頻率上升
        "declining_topics": [],   # 出題頻率下降
        "stable_topics": [],      # 穩定出現
        "new_topics": [],         # 新出現的主題
        "difficulty_trend": None  # 難度趨勢
    }
    
    return trends
```

---

## 📊 分析報告

```json
{
  "exam_type": "麻醉專科醫師考試",
  "years_analyzed": 5,
  "total_questions": 500,
  
  "topic_distribution": [
    {"topic": "藥理學", "percentage": 25.4, "questions": 127},
    {"topic": "呼吸管理", "percentage": 18.2, "questions": 91},
    {"topic": "心血管監測", "percentage": 15.6, "questions": 78},
    {"topic": "區域麻醉", "percentage": 12.8, "questions": 64}
  ],
  
  "high_yield_topics": [
    {
      "topic": "吸入麻醉劑",
      "importance_score": 0.92,
      "frequency": "每年必考",
      "avg_questions": 8
    },
    {
      "topic": "肌肉鬆弛劑",
      "importance_score": 0.88,
      "frequency": "每年必考",
      "avg_questions": 6
    }
  ],
  
  "trends": {
    "rising": ["ERAS", "POCD", "區域麻醉超音波"],
    "declining": ["傳統解剖定位", "吸入誘導"],
    "stable": ["藥物動力學", "監測原理"]
  },
  
  "difficulty_progression": {
    "2022": 0.62,
    "2023": 0.65,
    "2024": 0.68,
    "2025": 0.71,
    "trend": "逐年增加"
  }
}
```

---

## 📝 輸出格式

```
📊 考古題分析報告

考試類型: 麻醉專科醫師考試
分析範圍: 2021-2025 (5年)
題目總數: 500 題
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 高頻出題主題 (Top 10)

排名  主題              比例    題數   重要性
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1     藥理學            25.4%   127    ⭐⭐⭐⭐⭐
2     呼吸管理          18.2%    91    ⭐⭐⭐⭐⭐
3     心血管監測        15.6%    78    ⭐⭐⭐⭐
4     區域麻醉          12.8%    64    ⭐⭐⭐⭐
5     神經生理          8.4%     42    ⭐⭐⭐
...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 出題趨勢

上升趨勢 (近年出現更多):
├── 🆕 ERAS (Enhanced Recovery)
├── 🆕 術後認知功能障礙 (POCD)
└── 🆕 超音波引導區域麻醉

下降趨勢:
├── 📉 傳統解剖定位技術
└── 📉 吸入誘導

穩定出現 (每年必考):
├── ✓ 藥物動力學基本概念
├── ✓ 監測原理
└── ✓ 緊急狀況處理

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📉 難度趨勢

2021: ████████████░░░░░░░░ 62%
2022: █████████████░░░░░░░ 65%
2023: ██████████████░░░░░░ 68%
2024: ███████████████░░░░░ 71%
2025: ████████████████░░░░ 預估 73%

趨勢: 逐年增加 (+2.3%/年)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🎯 預測建議

```
💡 出題預測 (2026)

高機率出現:
├── Propofol 藥理 (連續5年)
├── Succinylcholine 禁忌症 (連續5年)
├── 惡性高熱處理 (連續4年)
└── 困難呼吸道演算法 (連續5年)

新興主題 (建議準備):
├── 術中神經監測 (近2年新增)
├── 目標導向輸液治療 (GDFT)
└── 麻醉深度監測 (BIS/Entropy)

歷年易錯題型:
├── 藥物交互作用計算
├── 評分量表解讀 (ASA, Mallampati)
└── 圖表判讀 (藥物濃度曲線)
```

