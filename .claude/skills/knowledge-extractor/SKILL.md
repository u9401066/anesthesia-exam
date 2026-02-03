````skill
---
name: knowledge-extractor
description: 從教材中抽取概念、實體、關係，建立知識圖譜。Triggers: 抽取概念, 知識抽取, 概念提取, extract concepts, 建立知識圖譜, knowledge graph.
version: 1.0.0
category: knowledge-processing
compatibility:
  - crush
  - claude-code
allowed-tools:
  - read_file
  - grep_search
  - source_lookup
---

# 知識抽取器 (Knowledge Extractor)

## 描述

從教材中抽取關鍵概念、實體、關係，支援 Multi-hop 題目生成和概念關聯分析。
參考 Ragas 的 Knowledge Graph 設計。

## 觸發條件

- 「抽取概念」「知識抽取」
- 「建立知識圖譜」
- 「extract concepts」

---

## 🔧 抽取流程

### Step 1: 命名實體識別 (NER)

```python
entities = []
for chunk in index.query(scope):
    # 抽取藥物、疾病、程序、解剖結構等
    ner_results = extract_entities(chunk.text, types=[
        "DRUG",        # 藥物名稱
        "DISEASE",     # 疾病
        "PROCEDURE",   # 醫療程序
        "ANATOMY",     # 解剖結構
        "DOSAGE",      # 劑量
        "EFFECT",      # 效果/副作用
    ])
    entities.extend(ner_results)
```

### Step 2: 關鍵詞組抽取

```python
keyphrases = []
for chunk in index.query(scope):
    # 抽取專業術語和概念
    phrases = extract_keyphrases(chunk.text)
    keyphrases.extend(phrases)
```

### Step 3: 關係建立

```python
# 建立實體間的關係
relationships = []
for entity_a, entity_b in entity_pairs:
    relation = detect_relation(entity_a, entity_b, context)
    # 例如: (Propofol, TREATS, 鎮靜)
    # 例如: (Propofol, CAUSES, 低血壓)
    relationships.append((entity_a, relation, entity_b))
```

### Step 4: 知識圖譜構建

```python
# 建立圖結構（用於 Multi-hop 題目）
graph = KnowledgeGraph()
for entity in entities:
    graph.add_node(entity)
for rel in relationships:
    graph.add_edge(rel.source, rel.target, rel.type)
```

---

## 📊 輸出結構

```json
{
  "extraction_id": "ext_20260203_001",
  "entities": [
    {
      "id": "e_001",
      "text": "Propofol",
      "type": "DRUG",
      "mentions": 45,
      "pages": [89, 90, 91, 95, 102]
    },
    {
      "id": "e_002",
      "text": "低血壓",
      "type": "EFFECT",
      "mentions": 12,
      "pages": [91, 92, 103]
    }
  ],
  "relationships": [
    {
      "source": "Propofol",
      "relation": "CAUSES",
      "target": "低血壓",
      "confidence": 0.95,
      "evidence_pages": [91, 92]
    },
    {
      "source": "Propofol",
      "relation": "USED_FOR",
      "target": "麻醉誘導",
      "confidence": 0.98,
      "evidence_pages": [89, 90]
    }
  ],
  "keyphrases": [
    "context-sensitive half-time",
    "effect-site concentration",
    "target-controlled infusion"
  ]
}
```

---

## 📝 輸出範例

```
🧠 知識抽取完成

📦 實體統計
├── 藥物 (DRUG): 23 個
├── 效果 (EFFECT): 45 個
├── 程序 (PROCEDURE): 18 個
├── 劑量 (DOSAGE): 32 個
└── 解剖 (ANATOMY): 15 個

🔗 關係統計
├── CAUSES (導致): 34 組
├── USED_FOR (用於): 28 組
├── CONTRAINDICATED (禁忌): 12 組
└── INTERACTS_WITH (交互): 8 組

🔑 核心概念 (Keyphrases)
├── context-sensitive half-time
├── effect-site concentration
├── target-controlled infusion
├── minimum alveolar concentration
└── blood-gas partition coefficient

💡 Multi-hop 題目潛力
├── 2-hop 關係: 156 組
└── 3-hop 關係: 89 組
```

````
