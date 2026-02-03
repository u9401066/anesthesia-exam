# 智慧考卷生成系統 - 完整規格書

> 建立日期: 2026-02-03  
> 最後更新: 2026-02-03  
> 狀態: 需求確認中

---

## 目錄

1. [專案概述](#1-專案概述)
2. [功能需求](#2-功能需求)
3. [技術架構](#3-技術架構)
4. [Instruction 結構設計](#4-instruction-結構設計)
5. [技術選型與 MVP](#5-技術選型與-mvp)
6. [討論議題追蹤](#6-討論議題追蹤)
7. [待驗證項目](#7-待驗證項目)
8. [附錄](#8-附錄)

---

## 1. 專案概述

### 1.1 目標

建立一個 Web 應用程式，讓**醫學專科考試考生**（首重台灣麻醉專科考試）可以：

1. **自動產生考卷** - 符合實際考試規格的模擬考卷
2. **線上作答練習** - 產生考卷後直接在系統上寫題
3. **PDF 下載** - 下載考卷 + 詳解 PDF
4. **獲得詳細解答** - 含精確來源追蹤（頁碼、行號、原文）
5. **互動式學習** - 類似 NotebookLM 的 AI 問答

### 1.2 應用領域

| 項目 | 內容 |
| ---- | ---- |
| 主要對象 | 台灣麻醉專科考試考生 |
| 教材來源 | 麻醉科教科書 PDF、歷年考古題 |
| 版權策略 | 學生僅取得 Agent 生成的考題與詳解，**不提供完整書本**（避免版權問題） |

### 1.3 核心特色

- **Agent 驅動** - 使用 GitHub Copilot SDK 或 OpenCode（支援 Skill + Instruction + Sub-agent）
- **精準來源追蹤** - 詳解標註頁碼、行數、原文引用
- **半編碼 Instruction** - 預設模板 + 後台結構化設定可調整
- **多媒體支援** - 支援從教材擷取圖片出題

### 1.4 系統整合架構

```
┌─────────────────────────────────────────────────────────────────┐
│                         完整系統架構                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────┐                                               │
│   │   Tools     │ ←── 可能成為 MCP Server                       │
│   │  (MCP?)     │     - PDF 解析                                │
│   │             │     - 圖片擷取                                │
│   │             │     - 來源追蹤                                │
│   └──────┬──────┘                                               │
│          │                                                      │
│          ▼                                                      │
│   ┌─────────────┐                                               │
│   │   Agent     │ ←── Copilot SDK / OpenCode                    │
│   │             │     - Skill 定義                              │
│   │             │     - Instruction 解析                        │
│   │             │     - Sub-agent 協調                          │
│   └──────┬──────┘                                               │
│          │                                                      │
│          ▼                                                      │
│   ┌─────────────┐                                               │
│   │     UI      │ ←── Open Notebook 改造 / Chainlit             │
│   │             │     - 考卷介面                                │
│   │             │     - 作答介面                                │
│   │             │     - 互動問答                                │
│   └──────┬──────┘                                               │
│          │                                                      │
│          ▼                                                      │
│   ┌─────────────┐                                               │
│   │ 文件處理    │ ←── asset-aware-mcp / 自有 repo               │
│   │             │     - PDF 解析保留頁碼                        │
│   │             │     - RAG 索引保留行號                        │
│   │             │     - 圖片擷取 + 圖說                         │
│   └─────────────┘                                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 功能需求

### 2.1 考卷生成模組

#### 2.1.1 考題參數設定

| 參數 | 說明 | 備註 |
| ---- | ---- | ---- |
| 題型 | 選擇題、填充題、問答題、計算題、圖片題等 | 透過 Skill 定義不同題型的出法 |
| 範圍 | 指定章節、單元、主題 | 基於 RAG 索引的教材範圍 |
| 配分 | 每題分數、總分設定 | 可依難度加權 |
| 觀念比重 | 各知識點的出題比例 | 透過 Instruction 設定 |
| 難度 | 簡單/中等/困難 | 參考歷年考古題難度 |
| 題數 | 各題型數量 | - |

#### 2.1.2 Skill 與 Instruction 架構

```
┌─────────────────────────────────────────────────────────────────┐
│                     Instruction (可編輯)                         │
│  - 出題風格設定                                                  │
│  - 難度分佈規則                                                  │
│  - 觀念比重配置                                                  │
│  - 題型配分規則                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   主 Agent (Orchestrator)                        │
│  - 解析 instruction                                              │
│  - 根據 skill 分派任務給 sub-agents                              │
└─────────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│ Skill:    │  │ Skill:    │  │ Skill:    │  │ Skill:    │
│ 選擇題    │  │ 問答題    │  │ 圖片題    │  │ 詳解生成  │
│ Sub-Agent │  │ Sub-Agent │  │ Sub-Agent │  │ Sub-Agent │
└───────────┘  └───────────┘  └───────────┘  └───────────┘
```

**Instruction 半編碼調整範例**：
- 4選1單選 20題 + 5選項多選 20題
- 總分 100 分
- 題組題 8 題
- 多選項選擇（ab, cde, abc, 以上皆是）佔 25%
- 考古題佔比 10%

### 2.2 作答練習模組（新增）

#### 2.2.1 核心功能

| 功能 | 說明 |
| ---- | ---- |
| 線上作答 | 產生考卷後直接在系統上作答 |
| 計時功能 | 可設定考試時間限制 |
| 即時批改 | 選擇題即時判斷對錯 |
| 詳解顯示 | 每題可展開查看詳解與來源 |
| 進度儲存 | 可暫停後繼續作答 |

#### 2.2.2 作答流程

```
產生考卷 → 預覽確認 → 開始作答 → 提交 → 批改 → 查看詳解
                         ↓
                    (可暫存進度)
```

### 2.3 PDF 下載模組（新增）

#### 2.3.1 下載內容

| 類型 | 內容 |
| ---- | ---- |
| 考卷 PDF | 純題目（可用於列印練習） |
| 答案卷 PDF | 正確答案（簡潔版） |
| 詳解 PDF | 完整詳解 + 來源標註 |
| 合併 PDF | 題目 + 詳解（供複習用） |

#### 2.3.2 PDF 格式要求

```json
{
  "exam_pdf": {
    "header": "麻醉專科模擬考 - 2026春季",
    "include_answer_sheet": true,
    "questions_per_page": 5,
    "image_quality": "high"
  },
  "solution_pdf": {
    "include_source_citation": true,
    "citation_format": "頁碼 P.{page}, 第 {line_start}-{line_end} 行",
    "include_original_text": true,
    "max_citation_length": 200
  }
}
```

### 2.4 詳解系統

#### 2.4.1 詳解內容結構

```json
{
  "answer": "正確答案",
  "explanation": "解題思路說明",
  "source": {
    "document": "教材名稱",
    "page": 42,
    "lines": "15-23",
    "original_text": "原文引用內容（避免過長，注意版權）"
  },
  "figure_caption": "若為圖片題，引用圖說",
  "related_concepts": ["相關概念1", "相關概念2"],
  "difficulty_analysis": "難度分析"
}
```

#### 2.4.2 來源追蹤技術分層

| 層次 | 責任 | 工具 |
| ---- | ---- | ---- |
| 層次 1：PDF 解析 | 解析內容、擷取圖片、輸出頁碼 | asset-aware-mcp / 自有 repo |
| 層次 2：索引/搜尋 | **行號追蹤** | GraphRAG / LightRAG / grep tool |

**方案選項**：

| 方案 | 說明 | 行號追蹤方式 |
| ---- | ---- | ---- |
| GraphRAG + 原子化切分 | 建立索引時原子化，每個 chunk 保留 line metadata | 索引時預計算 |
| LightRAG + 原子化切分 | 同上，較輕量 | 索引時預計算 |
| grep tool 動態搜尋 | 類似 Copilot grep，搜尋時計算位置 | 查詢時動態計算 |

### 2.5 圖片題支援

#### 2.5.1 優先順序

| Phase | 來源 | 說明 |
| ----- | ---- | ---- |
| Phase 1 | 從教材擷取 | 使用 PDF 解析工具擷取教材中的圖片 + 圖說 |
| Phase 2 | AI 生成 | DALL-E / Stable Diffusion |
| Phase 3 | 動態圖表 | Matplotlib / D3.js |

#### 2.5.2 圖片題類型

- 圖表解讀題：分析圖表數據（如藥物濃度曲線）
- 圖形辨識題：識別解剖結構、儀器設備
- 圖片配對題：圖文配對

### 2.6 互動學習模組

#### 2.6.1 功能優先級

| 功能 | 優先級 | 說明 |
| ---- | ------ | ---- |
| 文件上傳與分析 | P0 | 上傳教材 PDF |
| 對話式問答 | P0 | 針對題目/教材進行問答 |
| 引用來源標註 | P0 | 回答時標註頁碼行號（核心功能） |
| 重點摘要 | P1 | 自動生成學習重點 |
| 多文件整合 | P1 | 整合多本教材 |
| 概念圖生成 | P2 | 視覺化知識點關聯 |
| 學習路徑推薦 | P2 | 根據弱點推薦學習順序 |
| Audio Overview | P3 | 語音摘要（類似 NotebookLM） |

---

## 3. 技術架構

### 3.1 整體架構圖

```
┌──────────────────────────────────────────────────────────────────┐
│                        Frontend (Web App)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ 考卷生成介面 │  │ 作答練習介面 │  │ 互動問答介面 │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
│                    Open Notebook 改造 / Chainlit                  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Backend API                                │
└──────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Agent      │    │   Document   │    │   Database   │
│   Service    │    │   Service    │    │              │
│              │    │              │    │  (PostgreSQL │
│  Copilot SDK │    │  GraphRAG/   │    │   + Vector)  │
│  / OpenCode  │    │  LightRAG    │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
        │                   │
        ▼                   ▼
┌──────────────┐    ┌──────────────┐
│ Tools        │    │ asset-aware  │
│ (MCP Server?)│    │    -mcp      │
│              │    │ (PDF解析)    │
│ - grep tool  │    │              │
│ - source cite│    │              │
└──────────────┘    └──────────────┘
```

### 3.2 Agent SDK 選項

| SDK | 連結 | Skill | Instruction | Sub-agent |
| --- | ---- | ----- | ----------- | --------- |
| GitHub Copilot SDK | https://github.com/github/copilot-sdk | ✅ | ✅ copilot-instructions.md | ✅ |
| OpenCode | https://github.com/anomalyco/opencode | ✅ | ✅ 類似架構 | ✅ |
| LangGraph（備案） | https://github.com/langchain-ai/langgraph | ⚠️ 需自建 | ⚠️ 需自建 | ✅ |

**決策**：優先使用 Copilot SDK 或 OpenCode，LangGraph 僅作為備案

### 3.3 文件處理與索引流程

```
教材 PDF
    │
    ▼ (asset-aware-mcp / 自有 repo)
┌─────────────────────────────────┐
│  解析並保留 metadata            │
│  - 頁碼 (page)                  │
│  - 圖片 + 圖說                  │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  原子化切分 (for RAG)           │
│  - 保留 page/line metadata      │
│  - 建立 embedding               │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  索引儲存                       │
│  - GraphRAG 或 LightRAG         │
│  - Vector DB                    │
└─────────────────────────────────┘
```

---

## 4. Instruction 結構設計

### 4.1 設計理念

**半編碼調整** = 預設腳本 + 後台結構化設定覆蓋

```
預設 Instruction 模板 (麻醉專科考試標準格式)
              │
              ▼
後台結構化設定 (題型、配分、難度、比例)
              │
              ▼
最終 Instruction (合併後送給 Agent)
```

### 4.2 Instruction Schema（JSON 格式）

```json
{
  "exam_config": {
    "name": "麻醉專科模擬考 - 2026春季",
    "total_score": 100,
    "time_limit_minutes": 120
  },
  
  "question_types": {
    "single_choice": {
      "count": 20,
      "options_count": 4,
      "points_each": 2,
      "description": "4選1單選題"
    },
    "multiple_choice": {
      "count": 20,
      "options_count": 5,
      "points_each": 3,
      "description": "5選項多選題",
      "answer_format": ["ab", "cde", "abc", "以上皆是", "以上皆非"]
    },
    "question_set": {
      "count": 8,
      "questions_per_set": 3,
      "points_each": 2,
      "description": "題組題"
    }
  },
  
  "distribution": {
    "multiple_answer_style": {
      "percentage": 25,
      "description": "多選項選擇題佔比"
    },
    "past_exam": {
      "percentage": 10,
      "description": "考古題佔比"
    }
  },
  
  "difficulty": {
    "easy": 30,
    "medium": 50,
    "hard": 20
  },
  
  "scope": {
    "chapters": ["全部"],
    "emphasis": {
      "藥理學": 30,
      "生理學": 25,
      "臨床麻醉": 25,
      "疼痛醫學": 10,
      "重症照護": 10
    }
  },
  
  "source_requirements": {
    "must_cite_source": true,
    "include_page_number": true,
    "include_line_number": true,
    "include_original_text": true,
    "max_citation_length": 200
  },
  
  "image_questions": {
    "enabled": true,
    "count": 5,
    "source": "textbook_extract",
    "include_figure_caption": true
  }
}
```

### 4.3 預設模板範例

#### 麻醉專科標準考試模板

```json
{
  "template_id": "anesthesia_board_standard",
  "template_name": "麻醉專科標準考試",
  "exam_config": {
    "total_score": 100,
    "time_limit_minutes": 120
  },
  "question_types": {
    "single_choice": { "count": 40, "options_count": 4, "points_each": 2 },
    "multiple_choice": { "count": 10, "options_count": 5, "points_each": 2 }
  },
  "difficulty": { "easy": 20, "medium": 60, "hard": 20 },
  "distribution": { "past_exam": { "percentage": 20 } }
}
```

### 4.4 Instruction 與 Skill 的關係

```
Instruction (設定「要什麼」)          Skill (定義「怎麼做」)
─────────────────────────            ─────────────────────────
single_choice: 20題          ──→     skill_single_choice_generator
multiple_choice: 20題        ──→     skill_multiple_choice_generator
question_set: 8題            ──→     skill_question_set_generator
past_exam: 10%               ──→     skill_past_exam_retriever
image_questions: 5題         ──→     skill_image_question_generator
must_cite_source: true       ──→     skill_source_citation
```

---

## 5. 技術選型與 MVP

### 5.1 技術堆疊總覽（已確認）

| 層次 | 主要選擇 | 說明 | 狀態 |
| ---- | -------- | ---- | ---- |
| **Agent** | **OpenCode** | Go binary，透過 CLI + JSON 調用 | ✅ 確認 |
| **前端 UI** | **Streamlit** | 純 Python，你熟悉 | ✅ 確認 |
| **後端邏輯** | Open Notebook 複用 | 複用 RAG、chunking、embedding 邏輯 | ✅ 確認 |
| RAG 引擎 | LightRAG / Open Notebook 內建 | - | ⏳ 待驗證 |
| MCP Tools | asset-aware-mcp + 自建 | PDF 解析、來源追蹤 | ⏳ 待驗證 |
| LLM | Claude / OpenAI / Gemini | OpenCode 支援多 provider | ✅ |
| **Python 管理** | **uv** | 不使用 pip | ✅ 確認 |

### 5.1.1 OpenCode 安裝（Windows）

**問題**：OpenCode 沒有 Windows 預編譯版本

**解決方案選項**：

1. **安裝 Go 後編譯**（推薦）
   ```powershell
   # 1. 安裝 Go
   winget install GoLang.Go
   
   # 2. 重新開啟終端機後
   go install github.com/opencode-ai/opencode@latest
   
   # 3. 確認安裝
   opencode --help
   ```

2. **使用 WSL**
   ```bash
   # 在 WSL 內
   curl -fsSL https://raw.githubusercontent.com/opencode-ai/opencode/refs/heads/main/install | bash
   ```

3. **使用 Docker**
   ```powershell
   # 待補充
   ```

### 5.1.2 OpenCode 調用方式

```bash
# 非互動模式 + JSON 輸出
opencode -p "prompt" -f json -q -c /path/to/project
```

**關鍵能力**：
- `-p "prompt"` 單次執行
- `-f json` JSON 輸出（方便 Python 解析）
- `-q` 安靜模式（適合腳本）
- 支援 MCP servers 配置
- 內建 `agent` tool（sub-agent 能力）
- 支援 Claude, OpenAI, Gemini, Copilot 等多 provider

### 5.2 最終架構圖

```
┌─────────────────────────────────────────────────────────────────┐
│                     Streamlit (Python UI)                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ 考卷設定 │  │ 生成考卷 │  │ 線上作答 │  │  Chat    │        │
│  │ 介面     │  │ 預覽     │  │ 練習     │  │ 互動問答 │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Python Backend                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ OpenCode        │  │ Open Notebook   │  │ PDF Generator   │ │
│  │ Wrapper         │  │ 邏輯複用        │  │ (ReportLab)     │ │
│  │                 │  │                 │  │                 │ │
│  │ - subprocess    │  │ - chunking.py   │  │ - 考卷 PDF      │ │
│  │ - JSON 解析     │  │ - embedding.py  │  │ - 詳解 PDF      │ │
│  │ - Instruction   │  │ - search        │  │                 │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       ▼
┌──────────────────┐                    ┌──────────────────┐
│   OpenCode       │                    │   MCP Servers    │
│   (Go binary)    │                    │   (Tools)        │
│                  │                    │                  │
│   - Claude/GPT   │◄──── MCP ─────────►│  - PDF 解析      │
│   - agent tool   │      連接          │  - 圖片擷取      │
│   - grep/view    │                    │  - 來源追蹤      │
│   - 自動權限     │                    │  - asset-aware   │
└──────────────────┘                    └──────────────────┘
```

### 5.3 OpenCode 配置範例

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "your-api-key"
    }
  },
  "agents": {
    "coder": {
      "model": "claude-3.7-sonnet",
      "maxTokens": 8000
    }
  },
  "mcpServers": {
    "pdf-parser": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "asset_aware_mcp.server"]
    },
    "source-tracker": {
      "type": "stdio", 
      "command": "python",
      "args": ["-m", "source_tracker.server"]
    }
  }
}
```

### 5.4 MCP Tools 完整設計

#### 5.4.1 Tools 清單

| Tool 名稱 | 功能 | 參數 |
| --------- | ---- | ---- |
| `exam_storage.save` | 儲存題目到資料庫 | `questions: list`, `exam_id: str` |
| `exam_storage.load` | 讀取已生成的題目 | `exam_id: str`, `offset: int`, `limit: int` |
| `exam_storage.count` | 統計題目數量 | `exam_id: str`, `filters: dict` |
| `duplicate_check` | 檢查題目是否重複 | `question_text: str`, `threshold: float` |
| `source_lookup` | 查詢教材並返回來源 | `query: str`, `top_k: int` |
| `source_cite` | 格式化來源引用 | `doc: str`, `page: int`, `lines: str` |
| `progress_track.get` | 取得生成進度 | `exam_id: str` |
| `progress_track.update` | 更新生成進度 | `exam_id: str`, `completed: int`, `total: int` |
| `pdf_parse` | 解析 PDF 文件 | `file_path: str`, `extract_images: bool` |
| `image_extract` | 擷取指定圖片 | `doc: str`, `page: int`, `figure_id: str` |
| `past_exam_search` | 搜尋考古題 | `query: str`, `year_range: list` |

#### 5.4.2 連續生成 100 題的流程

```
Python Orchestrator 控制流程：

1. 初始化
   ├── 計算需要幾個 batch (100題 / 10題 = 10 batches)
   ├── 建立 exam_id
   └── 記錄開始時間

2. 迴圈生成 (for each batch)
   │
   ├── 構建 prompt
   │   └── 包含：已生成題目摘要 + 本批次要求 + 避免重複指示
   │
   ├── 調用 OpenCode
   │   opencode -p "{prompt}" -f json -q
   │   │
   │   └── OpenCode 內部可使用的 MCP Tools:
   │       ├── source_lookup: 查教材
   │       ├── duplicate_check: 檢查重複
   │       ├── image_extract: 取圖片（圖片題）
   │       └── past_exam_search: 搜考古題
   │
   ├── 驗證結果
   │   ├── JSON 格式正確？
   │   ├── 題目數量正確？
   │   └── 每題都有來源？
   │
   ├── 儲存結果
   │   └── exam_storage.save(questions, exam_id)
   │
   ├── 更新進度
   │   └── progress_track.update(exam_id, completed, total)
   │
   └── 錯誤處理
       ├── 重試機制 (max 3 次)
       └── 記錄失敗的 batch

3. 完成後
   ├── 最終去重檢查
   ├── 生成完整考卷 JSON
   └── 可選：生成 PDF
```

#### 5.4.3 Batch Prompt 設計

```python
def build_batch_prompt(exam_id: str, batch_num: int, config: dict) -> str:
    """構建單批次的 prompt"""
    
    # 取得已生成的題目摘要（避免重複）
    existing = exam_storage.load(exam_id)
    existing_summary = summarize_questions(existing)
    
    prompt = f"""
你是麻醉專科考試出題專家。請生成 {config['batch_size']} 道題目。

## 考卷配置
- 題型: {config['question_type']}
- 難度分佈: 簡單{config['easy']}% / 中等{config['medium']}% / 困難{config['hard']}%
- 範圍: {config['scope']}

## 已生成題目摘要（請避免重複）
{existing_summary}

## 產出格式
請使用 source_lookup tool 查詢教材，並用 source_cite tool 標註來源。
如果是圖片題，請使用 image_extract tool 擷取圖片。

輸出 JSON 格式：
{{
  "questions": [
    {{
      "id": "Q{batch_num * config['batch_size'] + 1}",
      "type": "single_choice",
      "question": "題目內容",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "A",
      "explanation": "詳解",
      "source": {{
        "document": "教材名稱",
        "page": 42,
        "lines": "15-23",
        "original_text": "原文引用"
      }},
      "difficulty": "medium",
      "image": null
    }}
  ]
}}
"""
    return prompt
```

#### 5.4.4 Python Orchestrator 實作

```python
import json
import subprocess
from dataclasses import dataclass
from typing import List, Optional
import time

@dataclass
class ExamConfig:
    total_questions: int = 100
    batch_size: int = 10
    question_type: str = "single_choice"
    easy: int = 30
    medium: int = 50
    hard: int = 20
    scope: List[str] = None
    max_retries: int = 3

class ExamGenerator:
    def __init__(self, config: ExamConfig):
        self.config = config
        self.exam_id = f"exam_{int(time.time())}"
        self.questions = []
        self.failed_batches = []
    
    def generate(self) -> dict:
        """連續生成完整考卷"""
        total_batches = self.config.total_questions // self.config.batch_size
        
        for batch_num in range(total_batches):
            print(f"生成中... Batch {batch_num + 1}/{total_batches}")
            
            success = False
            for attempt in range(self.config.max_retries):
                try:
                    result = self._generate_batch(batch_num)
                    if self._validate_batch(result):
                        self._save_batch(result)
                        success = True
                        break
                except Exception as e:
                    print(f"  重試 {attempt + 1}: {e}")
            
            if not success:
                self.failed_batches.append(batch_num)
                print(f"  ⚠️ Batch {batch_num} 失敗，稍後重試")
        
        # 重試失敗的 batches
        self._retry_failed_batches()
        
        # 最終去重
        self._deduplicate()
        
        return {
            "exam_id": self.exam_id,
            "questions": self.questions,
            "total": len(self.questions),
            "failed_batches": self.failed_batches
        }
    
    def _generate_batch(self, batch_num: int) -> dict:
        """調用 OpenCode 生成單批次"""
        prompt = self._build_prompt(batch_num)
        
        result = subprocess.run(
            ["opencode", "-p", prompt, "-f", "json", "-q"],
            capture_output=True,
            text=True,
            timeout=180  # 3分鐘 timeout
        )
        
        return json.loads(result.stdout)
    
    def _validate_batch(self, result: dict) -> bool:
        """驗證批次結果"""
        if "questions" not in result:
            return False
        
        for q in result["questions"]:
            # 檢查必要欄位
            required = ["question", "options", "answer", "explanation", "source"]
            if not all(k in q for k in required):
                return False
            
            # 檢查來源完整性
            if not q["source"].get("page"):
                return False
        
        return True
    
    def _save_batch(self, result: dict):
        """儲存批次結果"""
        self.questions.extend(result["questions"])
        
        # 也可以寫入資料庫/檔案作為 checkpoint
        checkpoint_file = f"./{self.exam_id}_checkpoint.json"
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(self.questions, f, ensure_ascii=False, indent=2)
    
    def _deduplicate(self):
        """去除重複題目"""
        seen = set()
        unique = []
        
        for q in self.questions:
            # 用題目前50字作為 key
            key = q["question"][:50]
            if key not in seen:
                seen.add(key)
                unique.append(q)
        
        self.questions = unique
```

### 5.4 MVP 功能階段

#### Phase 1 - 最小可行產品（Week 1-2）

| 功能 | 說明 | 技術 |
| ---- | ---- | ---- |
| PDF 上傳與解析 | 上傳教材 PDF，解析內容 | asset-aware-mcp |
| 原子化索引 | 建立帶行號的索引 | LightRAG |
| 單選題生成 | 根據範圍生成選擇題 | Agent |
| 詳解 + 來源標註 | 每題附上頁碼行號 | RAG retrieval |
| Chat 介面 | 基本問答 | Chainlit |

#### Phase 2 - 功能擴展（Week 3-4）

| 功能 | 說明 |
| ---- | ---- |
| 多題型 | 問答題、圖片題等 |
| 線上作答 | 產生考卷後直接作答 |
| PDF 下載 | 下載考卷 + 詳解 |
| Instruction 編輯 | 後台設定介面 |

#### Phase 3 - 完整功能（Week 5+）

| 功能 | 說明 |
| ---- | ---- |
| 考古題整合 | 歷年考題匯入分析 |
| 完整知識點體系 | 概念圖、知識點關聯 |
| 學習路徑推薦 | 根據弱點推薦 |
| Open Notebook 整合 | 完整 UI 改造 |

---

## 6. 討論議題追蹤

### 6.1 議題總覽

| 議題 | 狀態 | 備註 |
| ---- | ---- | ---- |
| Agent SDK 選型 | ⏳ 待驗證 | Copilot SDK vs OpenCode |
| 題目來源與詳解追蹤 | ⏳ 待 MCP 後補充 | RAG/grep 行號追蹤 |
| 圖片題生成 | ⏳ 待 MCP 後補充 | 優先從教材擷取 |
| 互動功能範圍 | ⏳ 待 MCP 後補充 | Open Notebook 改造 |
| MVP 範圍界定 | ✅ 已初步確認 | 見 Phase 1-3 |

### 6.2 已確認決策

| 項目 | 決策 |
| ---- | ---- |
| 應用領域 | 醫學（台灣麻醉專科考試） |
| 版權策略 | 學生僅獲得考題與詳解，不提供完整書本 |
| Agent SDK 候選 | GitHub Copilot SDK / OpenCode |
| 素材處理 | asset-aware-mcp + 自有 repo |
| 互動功能 | 基於 Open Notebook 修改 |
| 圖片題 | 優先從教材擷取 |
| RAG 行號追蹤 | RAG 索引時 或 grep tool 動態計算 |

### 6.3 討論記錄

**Session 1 - 2026-02-03**

討論內容：
- 初次需求梳理，建立規格書框架
- 確認應用領域：台灣麻醉專科考試
- 確認版權策略
- 確認 Agent SDK 方向
- 確認 Skill + Instruction 設計理念
- 釐清行號追蹤責任（RAG/grep，非 PDF 解析）
- 新增作答練習 + PDF 下載需求
- 確認系統整合架構：Tools(MCP?) + Agent + UI + 文件處理

---

## 7. 待驗證項目

### 7.1 技術驗證（優先）

| 優先 | 項目 | 目的 |
| ---- | ---- | ---- |
| 1 | GitHub Copilot SDK | 確認授權、skill/instruction 機制 |
| 2 | OpenCode | 確認功能完整度、與 SDK 比較 |
| 3 | LightRAG metadata | 確認可保留 page/line |
| 4 | asset-aware-mcp | 確認 PDF 解析能力 |

### 7.2 待決議事項

- [ ] Skill 定義來源：官方 Claude Code / 現有 repo / 自行開發
- [ ] Tools 是否做成 MCP Server？
- [ ] Instruction 編輯介面設計
- [ ] 版權策略：原文引用長度限制

### 7.3 開放問題

1. 行號追蹤精度：如何準確保留行號？
2. 圖片與文字關聯：如何建立圖片與周圍文字的關聯？
3. 題目驗證：生成的題目如何確保品質和正確性？
4. 考古題整合：如何將現有考古題匯入系統並建立關聯？

---

## 8. 附錄

### 8.1 開源資源清單

| 用途 | 名稱 | 連結 |
| ---- | ---- | ---- |
| Agent | GitHub Copilot SDK | https://github.com/github/copilot-sdk |
| Agent | OpenCode | https://github.com/anomalyco/opencode |
| Agent（備案） | LangGraph | https://github.com/langchain-ai/langgraph |
| RAG | LightRAG | https://github.com/HKUDS/LightRAG |
| 互動 UI | Open Notebook | https://github.com/lfnovo/open-notebook |
| Chat UI | Chainlit | https://github.com/Chainlit/chainlit |
| PDF 解析 | asset-aware-mcp | https://github.com/u9401066/asset-aware-mcp |
| PDF（備案） | PyMuPDF | https://github.com/pymupdf/PyMuPDF |
| Vector DB | pgvector | https://github.com/pgvector/pgvector |

### 8.2 名詞解釋

| 術語 | 說明 |
| ---- | ---- |
| Agent | 能夠自主執行任務的 AI 程式 |
| Skill | Agent 可執行的特定能力，如「選擇題生成」 |
| Instruction | 給 Agent 的指令或規範，可半編碼調整 |
| Sub-agent | 主 Agent 下的子代理，負責特定任務 |
| RAG | Retrieval-Augmented Generation，檢索增強生成 |
| MCP | Model Context Protocol，模型上下文協議 |

### 8.3 更新記錄

| 日期 | 更新內容 |
| ---- | -------- |
| 2026-02-03 | 初版規格書建立 |
| 2026-02-03 | 加入應用領域、Agent SDK 選項、素材處理工具 |
| 2026-02-03 | 釐清行號追蹤責任（RAG/grep 層） |
| 2026-02-03 | 新增作答練習、PDF 下載模組 |
| 2026-02-03 | 整合所有文件為單一 SPEC |

---

*此文件為持續更新的工作文件*
