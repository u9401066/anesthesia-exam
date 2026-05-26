---
name: exam-orchestrator
description: 考卷生成主編排器，解析考試配置並調度所有子 Skills 完成完整出題流程。Triggers: 生成考卷, 出考題, 模擬考, 產生試題, generate exam, create test, 出題, 考試, 測驗, quiz, exam, 製作考卷.
version: 1.0.0
category: exam-generation
compatibility:
  - crush
  - claude-code
  - github-copilot
dependencies:
  - knowledge-indexer
  - scope-analyzer
  - mcq-generator
  - essay-generator
  - question-set-generator
  - question-validator
  - difficulty-classifier
  - source-tracker
  - explanation-generator
  - exam-assembler
allowed-tools:
  - read_file
  - write_file
  - list_dir
  - grep_search
  - exam-generator__exam_save_question
  - exam-generator__exam_list_questions
  - exam-generator__exam_create_exam
  - exam-generator__exam_get_stats
---

# 考卷生成主編排器 (Exam Orchestrator)

## 描述

這是考題生成系統的**主控制器**，負責：
1. 解析考試配置 (Instruction)
2. 調度知識處理、出題、品質控制等子 Skills
3. 組裝最終考卷並輸出

## 觸發條件

- 「生成考卷」「出考題」「模擬考」
- 「產生 10 題選擇題」
- 「根據第三章出 5 題」
- 「generate exam」「create test」

---

## 🔧 完整流程

### Phase 1: 配置解析

```
輸入: 用戶指令 + Instruction 配置
輸出: 結構化的 ExamConfig
```

#### 預設 Instruction（若未指定）

```json
{
  "exam_name": "麻醉專科模擬考",
  "total_questions": 10,
  "question_types": {
    "mcq": { "count": 8, "options": 4 },
    "essay": { "count": 2 }
  },
  "difficulty_distribution": {
    "easy": 0.3,
    "medium": 0.5,
    "hard": 0.2
  },
  "scope": "all",
  "source_tracking": true
}
```

### Phase 2: 知識準備

```
調用 Skills:
├── knowledge-indexer  → 確認教材已索引
├── scope-analyzer     → 分析出題範圍
└── knowledge-extractor → 抽取關鍵概念（若需要）
```

#### 檢查教材索引

```python
# 確認 RAG 索引存在
if not index_exists(scope):
    調用 knowledge-indexer skill
    等待索引完成
```

### Phase 3: 題目生成

```
根據 question_types 調用對應 Skills:
├── mcq-generator      → 選擇題
├── essay-generator    → 問答題
├── question-set-generator → 題組題
└── image-question-generator → 圖片題
```

#### 生成流程

```python
for question_type, config in instruction.question_types:
    # 1. 調用對應生成器
    questions = generate(question_type, config)
    
    # 2. 品質控制
    questions = validate(questions)        # question-validator
    questions = classify(questions)        # difficulty-classifier
    questions = check_duplicate(questions) # duplicate-checker
    questions = track_source(questions)    # source-tracker
    
    # 3. 暫存
    save_questions(questions)
```

### Phase 4: 品質控制

```
對每題執行:
├── question-validator   → 格式、正確性檢查
├── difficulty-classifier → 確認難度標籤
├── duplicate-checker    → 檢查是否重複過去題目
└── source-tracker       → 確保來源完整
```

### Phase 5: 詳解生成

```
調用 Skills:
└── explanation-generator → 生成每題詳解
    ├── 解題思路
    ├── 知識點連結
    └── 來源引用（頁碼、行號）
```

### Phase 6: 考卷組裝

```
調用 Skills:
├── exam-assembler → 組裝成完整考卷
│   ├── 題目排序（依難度/主題）
│   ├── 配分計算
│   └── 格式化輸出
└── export-formatter → 匯出指定格式
    ├── JSON（內部使用）
    ├── PDF（列印用）
    ├── Markdown（預覽）
    └── QTI（LMS 匯入）
```

---

## 📊 流程圖

```
┌─────────────────────────────────────────────────────────────┐
│                    exam-orchestrator                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [1] 配置解析                                               │
│      └── 解析 Instruction → ExamConfig                      │
│                     ↓                                       │
│  [2] 知識準備                                               │
│      ├── knowledge-indexer (確認索引)                       │
│      ├── scope-analyzer (範圍分析)                          │
│      └── knowledge-extractor (概念抽取)                     │
│                     ↓                                       │
│  [3] 題目生成 (並行/批次)                                   │
│      ├── mcq-generator ───────┐                             │
│      ├── essay-generator ─────┤                             │
│      ├── question-set-gen ────┼──→ questions[]              │
│      └── image-question-gen ──┘                             │
│                     ↓                                       │
│  [4] 品質控制 (每題)                                        │
│      ├── question-validator                                 │
│      ├── difficulty-classifier                              │
│      ├── duplicate-checker                                  │
│      └── source-tracker                                     │
│                     ↓                                       │
│  [5] 詳解生成                                               │
│      └── explanation-generator                              │
│                     ↓                                       │
│  [6] 考卷組裝                                               │
│      ├── exam-assembler                                     │
│      └── export-formatter                                   │
│                     ↓                                       │
│  [OUTPUT] 完整考卷 (JSON/PDF/Markdown/QTI)                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎮 使用範例

### 基本使用

```
用戶: 生成 10 題選擇題

Orchestrator 行為:
1. 使用預設配置
2. 生成 10 題 MCQ
3. 自動分配難度 (3簡單/5中等/2困難)
4. 附加詳解和來源
```

### 指定範圍

```
用戶: 根據藥理學第三章出 5 題問答題

Orchestrator 行為:
1. scope-analyzer 分析「藥理學第三章」
2. essay-generator 生成 5 題問答
3. source-tracker 追蹤來源到第三章
```

### 完整配置

```
用戶: 按照以下配置生成考卷
{
  "mcq": 20,
  "essay": 5,
  "difficulty": { "easy": 20%, "medium": 60%, "hard": 20% },
  "scope": ["藥理學", "生理學"],
  "past_exam_ratio": 10%
}

Orchestrator 行為:
1. 解析完整配置
2. 分配生成任務
3. 調用 past-exam-matcher 混入 10% 考古題
4. 完整品質控制
5. 輸出考卷 + 答案 + 詳解
```

---

## 📝 輸出格式

```
🎓 考卷生成完成

📋 考卷資訊
├── 名稱: 麻醉專科模擬考 - 2026春季
├── 題數: 25 題
├── 總分: 100 分
└── 範圍: 藥理學、生理學

📊 題型分佈
├── 選擇題: 20 題 (80分)
└── 問答題: 5 題 (20分)

📈 難度分佈
├── 簡單: 5 題 (20%)
├── 中等: 15 題 (60%)
└── 困難: 5 題 (20%)

✅ 品質檢查
├── 格式驗證: 通過
├── 來源追蹤: 100% (25/25)
├── 重複檢查: 無重複
└── 難度校驗: 符合設定

📁 輸出檔案
├── exam_20260203_001.json (考卷資料)
├── exam_20260203_001_solutions.json (詳解)
└── exam_20260203_001.pdf (可選)

是否預覽考題？(y/n)
```

---

## ⚙️ MCP Tools 使用

此 Skill 會調用以下 MCP Tools:

| Tool | 用途 |
| ---- | ---- |
| `exam-generator__exam_save_question` | 儲存生成的題目 |
| `exam-generator__exam_list_questions` | 查詢已有題目 |
| `exam-generator__exam_create_exam` | 創建考卷記錄 |
| `exam-generator__exam_get_stats` | 獲取統計資訊 |
| `asset-aware__get_section_content` | 查詢教材來源 |
| `asset-aware__search_source_location` | 格式化來源引用 |

---

## 🔄 與其他 Skills 關係

```
exam-orchestrator (編排器)
├── 知識處理層
│   ├── knowledge-indexer
│   ├── knowledge-extractor
│   └── scope-analyzer
├── 出題生成層
│   ├── mcq-generator
│   ├── essay-generator
│   ├── question-set-generator
│   └── image-question-generator
├── 品質控制層
│   ├── question-validator
│   ├── difficulty-classifier
│   ├── duplicate-checker
│   └── source-tracker
├── 考古題層
│   ├── past-exam-analyzer
│   └── past-exam-matcher
└── 輸出層
    ├── explanation-generator
    ├── exam-assembler
    └── export-formatter
```

---

## ⚠️ 注意事項

1. **確保教材已索引**：生成前會檢查 RAG 索引
2. **來源追蹤必須**：每題都要有可驗證的來源
3. **難度要校驗**：使用 difficulty-classifier 確認
4. **考古題去重**：避免與考古題過度相似
5. **批次處理**：大量題目分批生成避免超時

