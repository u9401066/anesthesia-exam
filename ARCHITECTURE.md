# Architecture

智慧考卷生成系統 - 架構說明文檔

> 最後更新: 2026-04-15

---

## 系統概覽

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Streamlit Web Application                           │
├──────────────────┬─────────────────────────────┬────────────────────────────┤
│     Sidebar      │        Main Area            │       Right Panel          │
│  ┌────────────┐  │  ┌───────────────────────┐  │  ┌──────────────────────┐  │
│  │ 功能切換   │  │  │   考題作答區          │  │  │   Crush 對話區       │  │
│  │ ─ 生成考卷 │  │  │   ─ 流式生成顯示      │  │  │   ─ 即時對話         │  │
│  │ ─ 題庫瀏覽 │  │  │   ─ 題庫題目顯示      │  │  │   ─ 出題指令         │  │
│  │ ─ 考古題   │  │  │   ─ 作答互動          │  │  │   ─ 問答互動         │  │
│  ├────────────┤  │  ├───────────────────────┤  │  │   ─ 來源查詢         │  │
│  │ 出題設定   │  │  │   對答案/詳解區       │  │  └──────────────────────┘  │
│  │ ─ 題型     │  │  │   ─ 批改結果          │  │                            │
│  │ ─ 難度     │  │  │   ─ 詳解展開          │  │                            │
│  │ ─ 範圍     │  │  │   ─ 來源引用          │  │                            │
│  │ ─ 題數     │  │  └───────────────────────┘  │                            │
│  └────────────┘  │                              │                            │
└──────────────────┴─────────────────────────────┴────────────────────────────┘
```

---

## 核心模組架構

### 1. Web 工作台

目前 Web 介面集中在單一 Streamlit 工作台，由 `src/presentation/streamlit/app.py` 管理五個主頁面：

- `📝 生成考題`：教材索引、生成設定、來源模式分流、生成後審閱
- `✍️ 作答練習`：從題庫或剛生成題組立即開始練習與批改
- `📚 題庫管理`：搜尋 / 篩選 / reviewed-only / 切換成練習
- `📋 出題需求`：收集 backlog，並可觸發 heartbeat job emission
- `📊 統計`：查看題庫規模、難度分布與高頻主題

```
┌─────────────────────────────────────────────────────────────────┐
│                    Streamlit Workbench                           │
├──────────────────┬─────────────────────────────┬────────────────┤
│ Sidebar          │ Main Workspace              │ Shared Context │
│ - page nav       │ - generate                  │ - agent status │
│ - provider/model │ - practice                  │ - chat         │
│ - bank summary   │ - question bank             │ - ETL result   │
│                  │ - scope requests            │                │
│                  │ - statistics                │                │
└──────────────────┴─────────────────────────────┴────────────────┘
```

### 2. Agent / MCP 整合

Web 不直接綁死單一 Agent，而是透過 `src/infrastructure/agent/provider.py` 抽象出 provider 切換層。

```
┌─────────────────────────────────────────────────────────────────┐
│                  Streamlit app.py                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │ create_agent_provider()
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│            Agent Provider Abstraction                           │
├────────────────────┬───────────────────┬───────────────────────┤
│ Crush CLI          │ OpenCode CLI      │ Copilot SDK HTTP      │
└─────────┬──────────┴─────────┬─────────┴───────────┬───────────┘
          │                    │                     │
          ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Tooling                                 │
├──────────────────────────────┬──────────────────────────────────┤
│ exam-generator               │ asset-aware-mcp                 │
│ - question CRUD / audit      │ - ingest_documents              │
│ - validation / stats         │ - search_source_location        │
│ - past exam extraction       │ - consult_knowledge_graph       │
│ - blueprint scaffolding      │ - section / asset retrieval     │
└──────────────────────────────┴──────────────────────────────────┘
```

---

### 3. 大型 PDF 處理架構

> ⚠️ **挑戰**: Miller's Anesthesia 9th (~3500頁, ~500MB+)

目前大檔策略已經上浮到 Web ETL UI，可直接控制：

- `page_ranges`：先聚焦特定頁段，避免一開始整本 ingest
- `marker_max_pages_per_chunk`：控制大檔分塊頁數
- `extract_figures`：圖像很多時可先關閉，只保留文字 / blocks
- `use_marker`：正式來源追蹤必須開啟，否則會落到 preview-only

```
┌─────────────────────────────────────────────────────────────────┐
│                Large PDF Processing Pipeline                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Input: 2020 Miller's Anesthesia 9th.pdf (~500MB)              │
│        │                                                        │
│        ▼                                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Phase 1: Chunked Extraction (分批解析)                  │   │
│   │  ─ 每次處理 50-100 頁                                    │   │
│   │  ─ 記錄處理進度 (checkpoint)                             │   │
│   │  ─ 可暫停/續傳                                           │   │
│   └────────────────────┬────────────────────────────────────┘   │
│                        ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Phase 2: Content Extraction (內容提取)                  │   │
│   │                                                          │   │
│   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│   │  │  文字    │ │  圖片    │ │  表格    │ │  公式    │    │   │
│   │  │  提取    │ │  擷取    │ │  解析    │ │  識別    │    │   │
│   │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘    │   │
│   │       └────────────┴────────────┴────────────┘          │   │
│   └────────────────────┬────────────────────────────────────┘   │
│                        ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Phase 3: Atomic Chunking (原子化切分)                   │   │
│   │  ─ 每個 chunk 保留: page, line_start, line_end          │   │
│   │  ─ 圖片關聯: figure_id, caption, page                   │   │
│   │  ─ Chunk 大小: 512-1024 tokens                          │   │
│   └────────────────────┬────────────────────────────────────┘   │
│                        ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Phase 4: Embedding & Indexing                           │   │
│   │  ─ OpenAI / Local embedding model                       │   │
│   │  ─ Vector DB: Chroma / pgvector                         │   │
│   │  ─ Metadata 索引                                         │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   Output:                                                       │
│   ├── data/chunks/{doc_id}/*.json   (文字 chunks)               │
│   ├── data/images/{doc_id}/*.png    (提取的圖片)                 │
│   ├── data/index/{doc_id}.db        (向量索引)                  │
│   └── data/metadata/{doc_id}.json   (文檔元數據)                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 分批處理策略

```python
class LargeFileProcessor:
    """處理超大型 PDF 檔案"""
    
    BATCH_SIZE = 50  # 每批處理頁數
    CHECKPOINT_FILE = "processing_checkpoint.json"
    
    def process(self, pdf_path: Path) -> Generator[ProcessedChunk, None, None]:
        """分批處理，支援斷點續傳"""
        
        # 1. 讀取或建立 checkpoint
        checkpoint = self._load_checkpoint(pdf_path)
        start_page = checkpoint.get("last_processed", 0)
        
        # 2. 取得總頁數
        total_pages = self._get_page_count(pdf_path)
        
        # 3. 分批處理
        for batch_start in range(start_page, total_pages, self.BATCH_SIZE):
            batch_end = min(batch_start + self.BATCH_SIZE, total_pages)
            
            # 處理這批頁面
            chunks = self._process_pages(pdf_path, batch_start, batch_end)
            
            for chunk in chunks:
                yield chunk
            
            # 更新 checkpoint
            self._save_checkpoint(pdf_path, {"last_processed": batch_end})
            
            # 記憶體清理
            gc.collect()
```

---

### 4. DDD 分層架構

```
src/
├── domain/                      # 核心領域模型與 repository interface
│   ├── entities/
│   ├── repositories/
│   └── value_objects/
│
├── application/                 # 用例協調 / service orchestration
│   └── services/
│       ├── heartbeat_service.py
│       └── past_exam_extraction_service.py
│
├── infrastructure/              # 外部整合與持久化
│   ├── agent/
│   │   └── provider.py         # crush / opencode / copilot-sdk abstraction
│   ├── mcp/
│   │   └── exam_server.py      # exam-generator MCP tools
│   ├── persistence/
│   ├── crush/
│   └── logging/
│
└── presentation/
        └── streamlit/
                └── app.py              # Web 工作台入口
```

---

### 5. 核心資料流

#### 5.1 教材索引 / ETL

```
上傳 PDF
    → Streamlit ETL UI
    → Agent provider.run(prompt)
    → asset-aware ingest_documents
    → data/ 下產生 manifest / blocks / assets
    → 已索引教材回填到生成頁
```

#### 5.2 生成與審閱

```
選教材 / 章節 / 題數 / 難度
    → Agent provider 生成候選題
    → Web 顯示 preview 或 precise source badge
    → 人工編輯 / 審閱
    → SQLite 題庫持久化
```

#### 5.3 練習與題庫治理

```
題庫篩選
    → reviewed-only / topic / difficulty / exam_track
    → 抽題進入作答練習
    → 提交後即時計分
    → 查看詳解與來源
```

#### 5.4 Heartbeat 補題閉環

```
scope request backlog
    → HeartbeatService 分析缺口
    → data/jobs/*.json
    → 外部 agent 讀取 job 補題
    → 題目回存 SQLite / job 狀態回寫
```

### 6. 部署與啟動

目前正式啟動入口已統一為：

- `scripts/run_web.sh`
- `main.py`（走目前 Python interpreter 的 `python -m streamlit`）
- `deploy/systemd/anesthesia-exam-web.service`

部署時以 systemd service 為主，手動啟動僅作為開發與除錯用途。
       ↓
載入 mcq-generator/SKILL.md
       ↓
根據 Skill 定義執行出題流程
```
