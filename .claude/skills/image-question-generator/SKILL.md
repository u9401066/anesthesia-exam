````skill
---
name: image-question-generator
description: 圖片題生成器，從教材擷取圖片並生成相關題目。Triggers: 圖片題, 圖表題, 影像題, image question, 看圖辨識, 圖形題, 心電圖題, X光題.
version: 1.0.0
category: question-generation
compatibility:
  - crush
  - claude-code
allowed-tools:
  - image_extract
  - source_lookup
  - source_cite
  - exam_save_question
---

# 圖片題生成器 (Image Question Generator)

## 描述

從教材中擷取圖片（圖表、心電圖、X光、解剖圖等），並生成相關的視覺識別題目。

優先順序：
1. 從教材擷取現有圖片
2. AI 生成圖表（Phase 2）
3. 動態生成圖表（Phase 3）

## 觸發條件

- 「圖片題」「圖表題」「影像題」
- 「心電圖題」「X光題」
- 「看圖辨識」

---

## 🔧 生成流程

### Step 1: 圖片搜尋

```python
# 從索引中搜尋相關圖片
images = image_search(
    query=topic,
    scope=scope,
    types=["chart", "ecg", "xray", "anatomy", "diagram"]
)
```

### Step 2: 擷取圖片

```python
# 使用 MCP tool 擷取圖片
image_data = image_extract(
    document=doc_id,
    page=page_number,
    figure_id=figure_id
)

# 包含:
# - image_base64: 圖片資料
# - caption: 圖說
# - context: 周圍文字
```

### Step 3: 分析圖片內容

```python
# 使用視覺模型分析圖片
analysis = analyze_image(image_data, context={
    "caption": caption,
    "surrounding_text": context,
    "expected_topic": topic
})

# 輸出:
# - key_features: 關鍵特徵
# - labels: 標籤
# - clinical_significance: 臨床意義
```

### Step 4: 生成題目

```python
prompt = f"""
根據以下圖片生成題目：

【圖片資訊】
- 類型: {image_type}
- 圖說: {caption}
- 關鍵特徵: {key_features}

【題目要求】
- 難度: {difficulty}
- 題型: {question_type}

【輸出】
生成辨識/解讀該圖片的題目
"""
```

---

## 📊 題型範例

### 心電圖判讀題

```json
{
  "type": "image_mcq",
  "image_type": "ecg",
  "question": "請判讀此心電圖，最可能的診斷是？",
  "image": {
    "source": "Miller's Anesthesia",
    "page": 1256,
    "figure_id": "Fig 45-3",
    "caption": "Ventricular Tachycardia"
  },
  "options": [
    "A. 心室頻脈 (VT)",
    "B. 心房顫動 (AF)",
    "C. 心室顫動 (VF)",
    "D. 竇性心搏過速"
  ],
  "answer": "A",
  "key_features": [
    "寬 QRS 波 (>120ms)",
    "規則的 RR 間距",
    "心率約 180 bpm"
  ]
}
```

### 解剖圖辨識題

```json
{
  "type": "image_identification",
  "image_type": "anatomy",
  "question": "請標示圖中 A、B、C 所指的結構名稱。",
  "image": {
    "source": "Miller's Anesthesia",
    "page": 234,
    "figure_id": "Fig 12-5",
    "caption": "Brachial Plexus Anatomy"
  },
  "marked_points": ["A", "B", "C"],
  "answer": {
    "A": "上幹 (Upper Trunk)",
    "B": "中幹 (Middle Trunk)",
    "C": "下幹 (Lower Trunk)"
  }
}
```

### 藥物動力學曲線題

```json
{
  "type": "image_analysis",
  "image_type": "chart",
  "question": "根據此藥物濃度-時間曲線，下列敘述何者正確？",
  "image": {
    "source": "Miller's Anesthesia",
    "page": 567,
    "figure_id": "Fig 24-8",
    "caption": "Context-sensitive Half-time Comparison"
  },
  "options": [
    "A. Propofol 的 CSHT 隨輸注時間增加顯著上升",
    "B. Remifentanil 的 CSHT 與輸注時間無關",
    "C. Fentanyl 適合長時間輸注",
    "D. 所有藥物的 CSHT 都隨時間增加"
  ],
  "answer": "B"
}
```

---

## 📝 輸出格式

```
📷 圖片題生成完成

題目 #1 [心電圖判讀] [Medium] ━━━━━━━━━━━━━━

┌─────────────────────────────────────────┐
│                                         │
│        [ECG 圖片顯示區域]                │
│                                         │
│   (Fig 45-3: Ventricular Tachycardia)  │
│                                         │
└─────────────────────────────────────────┘

請判讀此心電圖，最可能的診斷是？

A. 心室頻脈 (Ventricular Tachycardia) ✓
B. 心房顫動 (Atrial Fibrillation)
C. 心室顫動 (Ventricular Fibrillation)
D. 竇性心搏過速 (Sinus Tachycardia)

🔑 關鍵特徵:
├── 寬 QRS 波 (>120ms)
├── 規則的 RR 間距
└── 心率約 180 bpm

📚 來源: Miller's Anesthesia P.1256
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🎯 圖片類型支援

| 類型 | 說明 | 題目方向 |
| ---- | ---- | -------- |
| ECG | 心電圖 | 判讀、診斷 |
| X-ray | X光片 | 辨識、定位 |
| CT/MRI | 斷層影像 | 解剖辨識 |
| Anatomy | 解剖圖 | 結構標示 |
| Chart | 圖表曲線 | 數據解讀 |
| Diagram | 流程/機制圖 | 概念理解 |
| Equipment | 設備照片 | 操作/識別 |

````
