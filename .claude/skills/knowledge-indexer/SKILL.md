````skill
---
name: knowledge-indexer
description: PDF 教材解析與 RAG 索引建立，保留頁碼和行號 metadata。Triggers: 索引教材, 解析 PDF, 建立索引, index, parse pdf, 上傳教材, 導入教材.
version: 1.0.0
category: knowledge-processing
compatibility:
  - crush
  - claude-code
allowed-tools:
  - read_file
  - write_file
  - list_dir
  - pdf_parse
  - source_lookup
---

# 知識索引器 (Knowledge Indexer)

## 描述

負責將 PDF 教材解析並建立 RAG 索引，**保留頁碼和行號 metadata** 以支援精準來源追蹤。

## 觸發條件

- 「索引教材」「解析 PDF」「建立索引」
- 「上傳教材」「導入教材」
- 「index textbook」「parse pdf」

---

## 🔧 處理流程

### Step 1: PDF 解析

```python
# 使用 asset-aware-mcp 或 PyMuPDF
parsed = pdf_parse(file_path, extract_images=True)
# 輸出:
# - pages[]: 每頁內容
# - images[]: 圖片 + 圖說
# - metadata: 頁碼、行號
```

### Step 2: 原子化切分

```python
chunks = []
for page in parsed.pages:
    for paragraph in page.paragraphs:
        chunk = {
            "text": paragraph.text,
            "metadata": {
                "document": file_name,
                "page": page.number,
                "line_start": paragraph.line_start,
                "line_end": paragraph.line_end,
                "chapter": detect_chapter(paragraph),
                "section": detect_section(paragraph)
            }
        }
        chunks.append(chunk)
```

### Step 3: 建立 Embedding

```python
# 使用 LightRAG 或 OpenAI Embedding
for chunk in chunks:
    chunk["embedding"] = embed(chunk["text"])
```

### Step 4: 儲存索引

```python
# 儲存到向量資料庫
index.add(chunks)
# 儲存 metadata 映射
save_metadata_map(document_id, chunks)
```

---

## 📊 Metadata 結構

```json
{
  "chunk_id": "ch_001",
  "text": "Propofol 是一種靜脈麻醉藥...",
  "embedding": [0.1, 0.2, ...],
  "metadata": {
    "document": "Miller's Anesthesia 9th",
    "page": 42,
    "line_start": 15,
    "line_end": 23,
    "chapter": "第三章 靜脈麻醉藥",
    "section": "3.2 Propofol",
    "has_image": false,
    "image_ref": null
  }
}
```

---

## 📝 輸出

```
📚 教材索引完成

├── 文件: Miller's Anesthesia 9th Edition.pdf
├── 頁數: 2,456 頁
├── 章節: 48 章
├── 切分: 12,345 個 chunks
├── 圖片: 892 張（含圖說）
└── 索引大小: 156 MB

✅ Metadata 保留
├── 頁碼追蹤: 100%
├── 行號追蹤: 100%
└── 章節標記: 100%

索引 ID: idx_miller_9th_20260203
```

````
