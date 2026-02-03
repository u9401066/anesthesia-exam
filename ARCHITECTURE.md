# Architecture

智慧考卷生成系統 - 架構說明文檔

> 最後更新: 2026-02-03

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

### 1. Question Source 模組（題目來源）

```
┌─────────────────────────────────────────────────────────────────┐
│                    Question Source Module                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────────┐    ┌─────────────────────┐            │
│   │  Streaming Source   │    │   Batch Source      │            │
│   │  (即時流式生成)      │    │   (題庫批次取得)     │            │
│   ├─────────────────────┤    ├─────────────────────┤            │
│   │ ■ Crush Agent 調用   │    │ ■ JSON 檔案讀取     │            │
│   │ ■ SSE 串流輸出       │    │ ■ SQLite/PostgreSQL │            │
│   │ ■ 即時顯示題目       │    │ ■ 隨機/篩選取題     │            │
│   │ ■ 進度條追蹤        │    │ ■ 一次載入全部      │            │
│   └──────────┬──────────┘    └──────────┬──────────┘            │
│              │                          │                       │
│              └────────────┬─────────────┘                       │
│                           ▼                                     │
│              ┌─────────────────────┐                            │
│              │  Unified Interface  │                            │
│              │  QuestionProvider   │                            │
│              └─────────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

#### Streaming Source (流式來源)

```python
class StreamingQuestionSource:
    """Crush Agent 即時生成題目"""
    
    async def generate(self, config: ExamConfig) -> AsyncGenerator[Question, None]:
        """流式生成題目，逐題 yield"""
        async for chunk in self.crush_client.stream(prompt):
            question = self.parser.parse_streaming(chunk)
            if question.is_complete:
                yield question
```

#### Batch Source (批次來源)

```python
class BatchQuestionSource:
    """從題庫批次取得題目"""
    
    def fetch(self, filters: QuestionFilters, limit: int) -> List[Question]:
        """一次取得所有題目"""
        return self.repository.find_by_filters(filters, limit)
```

---

### 2. Crush Agent 整合

```
┌─────────────────────────────────────────────────────────────────┐
│                      Crush Integration                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Streamlit UI                                                   │
│        │                                                        │
│        ▼                                                        │
│   ┌─────────────────┐                                           │
│   │  CrushClient    │  Python wrapper for Crush CLI             │
│   │  ─ streaming.py │  subprocess + StreamingParser             │
│   └────────┬────────┘                                           │
│            │                                                    │
│            ▼ (subprocess call)                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  D:\workspace260203\crush\crush.exe                      │   │
│   │  ─ config: crush.json                                   │   │
│   │  ─ skills_paths: [".claude/skills"]                     │   │
│   │  ─ MCP: exam-generator server                           │   │
│   └────────┬────────────────────────────────────────────────┘   │
│            │                                                    │
│            ▼ (MCP protocol)                                     │
│   ┌─────────────────┐                                           │
│   │  MCP Exam Server │  src/infrastructure/mcp/exam_server.py  │
│   │  ─ save_question │                                          │
│   │  ─ list_questions│                                          │
│   │  ─ get_question  │                                          │
│   │  ─ delete        │                                          │
│   └─────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

### 3. 大型 PDF 處理架構

> ⚠️ **挑戰**: Miller's Anesthesia 9th (~3500頁, ~500MB+)

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
├── domain/                    # 核心領域 (無外部依賴)
│   ├── entities/
│   │   ├── question.py       # Question, QuestionType, Difficulty
│   │   ├── exam.py           # Exam, ExamConfig
│   │   ├── source.py         # Source (page, lines, text)
│   │   └── conversation.py   # Conversation, Message
│   ├── value_objects/
│   │   └── source_citation.py
│   └── repositories/
│       └── question_repository.py  # Abstract interface
│
├── application/               # 應用層 (用例編排)
│   ├── services/
│   │   ├── question_source_service.py   # Streaming + Batch
│   │   ├── exam_generation_service.py   # 出題流程
│   │   └── grading_service.py           # 批改服務
│   └── use_cases/
│       ├── generate_exam.py
│       ├── answer_question.py
│       └── grade_exam.py
│
├── infrastructure/            # 基礎設施 (外部依賴)
│   ├── crush/
│   │   ├── client.py         # Crush CLI wrapper
│   │   └── streaming.py      # SSE streaming parser
│   ├── mcp/
│   │   └── exam_server.py    # MCP exam tools
│   ├── persistence/
│   │   ├── json_repository.py
│   │   └── sqlite_repository.py
│   └── pdf/
│       ├── large_file_processor.py  # 大檔案處理
│       └── chunker.py               # 原子化切分
│
└── presentation/              # 呈現層
    └── streamlit/
        ├── app.py            # 主程式入口
        ├── layouts/
        │   └── three_panel.py  # 三欄佈局
        ├── components/
        │   ├── sidebar.py      # 左側欄
        │   ├── exam_area.py    # 中央考題區
        │   └── chat_panel.py   # 右側對話區
        └── pages/
            ├── home.py
            ├── generate.py
            └── practice.py
```

---

### 5. Skills 架構

```
.claude/skills/
├── 主編排器
│   └── exam-orchestrator/     # 完整出題流程編排
│
├── 知識處理層
│   ├── knowledge-indexer/     # PDF 解析與 RAG 索引
│   ├── scope-analyzer/        # 範圍分析
│   └── knowledge-extractor/   # 概念抽取
│
├── 出題生成層
│   ├── mcq-generator/         # 選擇題
│   ├── essay-generator/       # 問答題
│   ├── question-set-generator/# 題組題
│   └── image-question-generator/ # 圖片題
│
├── 品質控制層
│   ├── question-validator/    # 題目驗證
│   ├── difficulty-classifier/ # 難度分類
│   ├── duplicate-checker/     # 重複檢查
│   └── source-tracker/        # 來源追蹤
│
├── 考古題層
│   ├── past-exam-analyzer/    # 考古題分析
│   └── past-exam-matcher/     # 考古題比對
│
└── 輸出層
    ├── explanation-generator/ # 詳解生成
    ├── exam-assembler/        # 試卷組裝
    └── export-formatter/      # 匯出格式
```

---

### 6. Memory Bank

| 文件 | 用途 |
|------|------|
| `activeContext.md` | 當前工作焦點 |
| `progress.md` | 進度追蹤 |
| `decisionLog.md` | 決策記錄 |
| `productContext.md` | 專案上下文 |
| `projectBrief.md` | 專案簡介 |
| `systemPatterns.md` | 系統模式 |
| `architect.md` | 架構設計 |

---

## 資料流

### 流式生成流程

```
1. 用戶設定出題參數 (Sidebar)
2. 點擊「開始生成」
3. StreamingQuestionSource.generate()
4. Crush Agent 收到 prompt
5. Crush 載入相關 Skills
6. 逐題生成並 yield
7. UI 即時顯示進度
8. 完成後儲存到題庫
```

### 題庫作答流程

```
1. 用戶從題庫選擇範圍
2. BatchQuestionSource.fetch()
3. 一次載入所有題目
4. 用戶作答
5. 提交批改
6. 顯示詳解與來源
```

---

## Crush Skill 觸發機制

Crush 透過 [Agent Skills](https://agentskills.io/) 標準觸發 Skills：

1. **自動檢測**：Crush 解析 `.claude/skills/*/SKILL.md` 的 frontmatter
2. **關鍵詞匹配**：根據 `description` 欄位的觸發詞匹配
3. **載入執行**：匹配成功後載入完整 Skill 內容

**範例觸發**：

```
用戶: "生成 10 題選擇題"
       ↓
Crush 解析 → 匹配 "選擇題" 觸發詞
       ↓
載入 mcq-generator/SKILL.md
       ↓
根據 Skill 定義執行出題流程
```
