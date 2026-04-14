# 🏗️ 系統重構規劃：Web App + Exam MCP 分離

> **日期**：2026-04-13
> **狀態**：Draft - 待討論確認

---

## 一、現況分析

### 目前架構的問題

```
目前的 Monolith：
┌───────────────────────────────────────────────────┐
│ Streamlit App (presentation/streamlit/app.py)     │
│  ├─ 考題管理 UI ✅                                │
│  ├─ 作答練習 UI ✅                                │
│  ├─ Agent 嵌入 (Crush/OpenCode/Copilot) ❌ 緊耦合 │
│  ├─ 流式生成邏輯 ❌ 與 UI 混合                     │
│  ├─ MCP 結果解析 ❌ 在 UI 層做                     │
│  └─ Prompt 模板管理 ❌ 硬編碼在 UI                  │
├───────────────────────────────────────────────────┤
│ exam-generator MCP (13 工具) ✅ 獨立運作           │
│ asset-aware MCP (~20 工具)   ✅ 獨立運作           │
├───────────────────────────────────────────────────┤
│ Domain Layer (entities/repos) ✅ 乾淨              │
│ SQLite Persistence            ✅ 完整              │
└───────────────────────────────────────────────────┘
```

**核心痛點**：
1. 把通用型 Agent (Crush/OpenCode) 嵌入 Web App 極度困難，維護成本高
2. Agent Provider 抽象層 3 種實現都需要在 Web App 內維護
3. 流式生成邏輯 (~300 行) 與 Streamlit UI 混在一起
4. Prompt 模板硬編碼在 UI 中，Agent 端無法獨立使用
5. 題目提取邏輯 (JSON/Markdown 解析) 不應在前端

---

## 二、重構目標架構

```
┌─────────────────────────────────────────────────────────────────────┐
│                        使用者 / 考生                                 │
│                            │                                        │
│                            ▼                                        │
│  ┌─────────────────────────────────────────┐                        │
│  │     Part 1: Web App (考題管理平台)        │                        │
│  │     ─────────────────────────────────    │                        │
│  │  • 題庫瀏覽/搜尋/篩選                    │                        │
│  │  • 手動新增/編輯考題                      │                        │
│  │  • 線上作答練習 + 即時批改                │                        │
│  │  • 考卷組裝 + PDF 匯出                   │                        │
│  │  • 統計儀表板                            │                        │
│  │  • 題目驗證/審閱介面                      │                        │
│  │  ❌ 不嵌入 Agent                         │                        │
│  │  ❌ 不做 AI 生成                         │                        │
│  └──────────────┬──────────────────────────┘                        │
│                  │ SQLite (共用資料庫)                                │
│                  │                                                   │
│  ┌──────────────┴──────────────────────────┐                        │
│  │     Part 2: Exam MCP (考題生成伺服器)     │                        │
│  │     ─────────────────────────────────    │                        │
│  │  • exam_save_question (含來源追蹤)       │                        │
│  │  • exam_list / search / get / stats     │                        │
│  │  • exam_validate / mark_validated       │                        │
│  │  • exam_create_exam (組卷)              │                        │
│  │  • exam_update / delete / restore       │                        │
│  │  • exam_get_audit_log                   │                        │
│  │  + NEW: exam_generate_prompt (提示模板)  │                        │
│  │  + NEW: exam_get_scope (範圍/知識點)     │                        │
│  └──────────────────────────────────────────┘                        │
│                  ▲                                                   │
│                  │ MCP Protocol (stdio)                              │
│                  │                                                   │
│  ┌──────────────┴──────────────────────────┐                        │
│  │     任意通用型 Agent                      │                        │
│  │  • GitHub Copilot (Agent Mode)           │                        │
│  │  • Claude Code / Claude Desktop          │                        │
│  │  • Codex CLI                             │                        │
│  │  • Cursor / Windsurf                     │                        │
│  │  • OpenCode / Crush                      │                        │
│  └──────────────┬──────────────────────────┘                        │
│                  │ MCP Protocol (stdio)                              │
│                  ▼                                                   │
│  ┌──────────────────────────────────────────┐                        │
│  │     asset-aware MCP (文獻解析)            │  ← 已完成              │
│  │  • ingest_documents (PDF → 索引)         │                        │
│  │  • consult_knowledge_graph (RAG)         │                        │
│  │  • search_source_location (精確定位)      │                        │
│  │  • get_section_content / blocks          │                        │
│  └──────────────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三、Part 1 - Web App（考題管理平台）

### 3.1 定位

一個**純前端管理平台**，不嵌入任何 Agent，專注於：
- 考題的 CRUD 管理
- 線上作答練習
- 考卷組裝與匯出
- 統計分析

### 3.2 技術選型

| 選項 | 方案 | 優缺點 |
|------|------|--------|
| **A. 維持 Streamlit** | 砍掉 Agent 相關程式碼，保留管理功能 | ✅ 最快，現有 UI 可復用 70%<br>❌ Streamlit 限制多 (無路由/狀態管理弱) |
| **B. FastAPI + Jinja2** | 輕量 SSR Web App | ✅ 標準 Python Web<br>✅ REST API 可供其他前端<br>❌ 需重寫 UI |
| **C. FastAPI + React/Vue** | 前後端分離 SPA | ✅ 最佳 UX<br>❌ 開發量最大 |

**建議**：**方案 A（短期）→ 方案 B（中期）**

短期先砍 Streamlit 中的 Agent 邏輯，快速得到乾淨的管理平台；
中期加上 FastAPI REST API 層，讓 Web App 和 MCP 都通過同一個 API 存取資料。

### 3.3 Web App 功能矩陣

| 功能 | 現有狀態 | 重構動作 |
|------|---------|---------|
| 📝 **手動新增考題** | ❌ 無（只靠 Agent） | 🆕 新增表單頁面 |
| 📝 **編輯考題** | ⚠️ 部分（審閱表單） | 🔧 強化為完整編輯器 |
| 📚 **題庫瀏覽** | ✅ 有（展開卡片） | 🔧 加分頁 + 篩選 + 排序 |
| 🔍 **搜尋** | ⚠️ FTS5 後端有，UI 未接 | 🔧 接上搜尋 UI |
| ✍️ **作答練習** | ✅ 完整 | ✅ 保留 |
| 📊 **統計** | ✅ 完整 | ✅ 保留 |
| 📄 **PDF 匯出** | ⚠️ 框架在，未接 reportlab | 🔧 實現 |
| 🗂️ **考卷組裝** | ⚠️ MCP 有 create_exam | 🆕 UI 化 |
| ✅ **題目驗證** | ⚠️ MCP 有，UI 未接 | 🔧 接上 |
| 📋 **審計記錄** | ✅ 後端完整 | 🆕 新增查看 UI |
| 🤖 **Agent 生成** | ❌ 移除 | ✂️ 移除 |
| 💬 **Chat 面板** | ❌ 移除 | ✂️ 移除 |
| 📤 **PDF 上傳** | ❌ 移除（改由 Agent 操作 MCP） | ✂️ 移除 |

### 3.4 Web App 頁面重設計

```
📱 考題管理平台
├── 🏠 首頁/儀表板
│   ├── 題庫總覽統計 (題數、難度分布、知識點分布)
│   ├── 最近新增題目
│   └── 快速操作按鈕
│
├── 📚 題庫管理
│   ├── 列表/卡片 切換檢視
│   ├── 篩選 (難度/題型/知識點/驗證狀態)
│   ├── 全文搜尋
│   ├── 批次操作 (刪除/標記驗證)
│   └── 每題：檢視/編輯/刪除/來源資訊/審計記錄
│
├── ➕ 新增/編輯考題
│   ├── 完整表單 (題文/選項/答案/詳解/難度/知識點)
│   ├── 來源資訊填寫 (教材/頁碼/原文)
│   ├── 即時預覽
│   └── 格式驗證
│
├── 📝 考卷管理
│   ├── 建立考卷 (手選/自動選題)
│   ├── 考卷列表
│   ├── 考卷預覽 + PDF 匯出
│   └── 考卷配置 (時間/分數/排版)
│
├── ✍️ 作答練習
│   ├── 選擇題庫範圍
│   ├── 互動答題
│   ├── 即時批改 + 詳解
│   └── 成績統計
│
└── 📊 統計分析
    ├── 題目分布 (難度/題型/知識點)
    ├── 來源分布 (教材/章節)
    ├── 時間趨勢
    └── 驗證率
```

### 3.5 可參考的開源專案

| 專案 | 特點 | 參考價值 |
|------|------|---------|
| **[quiz-app (Streamlit)](https://github.com/sven-nm/quiz-app)** | Streamlit 做的問答系統 | UI 模式參考 |
| **[Quilgo](https://quilgo.com/)** (商業) | 線上考試平台 | UX 設計參考 |
| **[ExamTopics](https://www.examtopics.com/)** (商業) | 題庫瀏覽 + 練習 | 題庫 UI 參考 |
| **[Open Quiz](https://github.com/deepanprabhu/streamlit-quiz)** | Streamlit Quiz | 作答 UI 元件 |
| **[ClassQuiz](https://github.com/mawoka-myblock/ClassQuiz)** | FastAPI+SvelteKit 完整考試平台 | 中期方案 B 參考 |

---

## 四、Part 2 - Exam MCP（考題生成 MCP 伺服器）

### 4.1 定位

一個**獨立的 MCP Server**，任何支援 MCP 的 Agent 都能直接使用來生成、管理考題。

### 4.2 現有工具盤點 (已完成 ✅)

```
exam-generator MCP (13 tools)
├── 📝 CRUD
│   ├── exam_save_question      ✅ 精確來源追蹤
│   ├── exam_get_question       ✅
│   ├── exam_list_questions     ✅ 篩選
│   ├── exam_update_question    ✅ 部分更新 + 審計
│   ├── exam_delete_question    ✅ 軟刪除
│   └── exam_restore_question   ✅
│
├── 🔍 查詢
│   ├── exam_search             ✅ FTS5 全文搜尋
│   └── exam_get_stats          ✅ 統計
│
├── ✅ 驗證
│   ├── exam_validate_question  ✅ 格式驗證
│   └── exam_mark_validated     ✅ 標記通過
│
├── 📋 審計
│   └── exam_get_audit_log      ✅ 完整歷史
│
└── 📄 考卷
    └── exam_create_exam        ✅ 隨機組卷
```

### 4.3 需要新增的工具

| 新工具 | 用途 | 優先級 |
|--------|------|--------|
| **exam_get_generation_guide** | 返回出題指引 + Prompt 模板，讓 Agent 知道正確流程 | 🔴 高 |
| **exam_get_topics** | 返回系統中所有知識點+題數，幫助 Agent 選擇出題方向 | 🔴 高 |
| **exam_bulk_save** | 批次儲存多題（減少 Agent 來回次數） | 🟡 中 |
| **exam_check_duplicate** | 檢查相似題目避免重複 | 🟡 中 |
| **exam_export_exam** | 匯出考卷為 JSON/Markdown | 🟡 中 |
| **exam_get_question_template** | 返回題目 JSON Schema，讓 Agent 知道完整結構 | 🔴 高 |

### 4.4 出題指引工具設計 (`exam_get_generation_guide`)

**這是最關鍵的新工具**。它讓任何 Agent 都能正確出題，不需要靠 Prompt 硬編碼。

```python
@mcp.tool()
async def exam_get_generation_guide(
    question_type: str = "mcq",      # mcq | essay | question_set
    with_source: bool = True,         # 是否需要來源追蹤
    language: str = "zh-TW"           # 語言
) -> str:
    """
    返回出題的完整指引，包含：
    1. 正確的出題流程（MCP 工具調用順序）
    2. 題目 JSON Schema
    3. 品質要求
    4. 來源追蹤規範
    5. 常見錯誤與避免方式
    """
    return GENERATION_GUIDE_TEMPLATE.format(...)
```

Agent 使用流程：
```
Agent 收到「出5題選擇題」指令
  ↓
① exam_get_generation_guide(question_type="mcq")
  → 取得完整出題指引 + JSON Schema
  ↓
② consult_knowledge_graph("麻醉藥理")           # asset-aware MCP
  → 取得相關知識內容
  ↓
③ search_source_location(doc_id, "propofol")    # asset-aware MCP
  → 取得精確來源 (page, line, original_text)
  ↓
④ exam_save_question({                           # exam MCP
     question_text: "...",
     options: [...],
     correct_answer: "A",
     stem_source: { page: 342, ... },
     ...
   })
  → 儲存成功，返回 question_id
  ↓
⑤ 重複 ②③④ 直到 5 題完成
```

### 4.5 MCP 配置範例

Agent 只需在設定檔中加入兩個 MCP：

**GitHub Copilot (`~/.config/github-copilot/mcp.json`)**:
```json
{
  "servers": {
    "exam-generator": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/anesthesia-exam", 
               "python", "-m", "src.infrastructure.mcp.exam_server"],
      "env": {
        "EXAM_DB_PATH": "/path/to/anesthesia-exam/data/exam.db"
      }
    },
    "asset-aware": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/anesthesia-exam/libs/asset-aware-mcp",
               "python", "-m", "src.presentation.server"],
      "env": {
        "ASSET_AWARE_DATA_DIR": "/path/to/anesthesia-exam/data"
      }
    }
  }
}
```

**Claude Desktop (`claude_desktop_config.json`)**:
```json
{
  "mcpServers": {
    "exam-generator": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/anesthesia-exam",
               "python", "-m", "src.infrastructure.mcp.exam_server"]
    },
    "asset-aware": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/anesthesia-exam/libs/asset-aware-mcp",
               "python", "-m", "src.presentation.server"]
    }
  }
}
```

**Crush / OpenCode (`crush.json` / `opencode.json`)**：
```json
{
  "mcp": {
    "exam-generator": {
      "command": "uv run python -m src.infrastructure.mcp.exam_server"
    },
    "asset-aware": {
      "command": "uv run -C libs/asset-aware-mcp python -m src.presentation.server"
    }
  }
}
```

---

## 五、實施計畫

### Phase 1：解耦 + 清理（~2-3 小時）

> 目標：把 Streamlit 中的 Agent 邏輯全部移除，得到乾淨的管理平台

| # | 任務 | 影響檔案 |
|---|------|---------|
| 1.1 | 移除 Agent Provider 層 (Crush/OpenCode/Copilot) | `src/infrastructure/agent/` |
| 1.2 | 移除 Streamlit 中的 Agent 相關程式碼 | `app.py` |
|     | - 移除 stream_agent_generate() | |
|     | - 移除 stream_agent_response() | |
|     | - 移除 run_agent_sync() | |
|     | - 移除右側 Chat 面板 | |
|     | - 移除 Agent 連線狀態 sidebar | |
|     | - 移除 Prompt 建構邏輯 | |
|     | - 移除流式生成預覽 | |
| 1.3 | 移除題目提取邏輯 | `app.py` |
|     | - 移除 extract_questions_from_response() | |
|     | - 移除 parse_mcp_result() | |
|     | - 移除 parse_question_from_output() | |
| 1.4 | 移除 Crush streaming client | `src/infrastructure/crush/` |
| 1.5 | 清理 pyproject.toml (移除 agent 依賴) | `pyproject.toml` |
| 1.6 | 更新 crush.json / opencode.json | 設定檔 |

### Phase 2：Web App 強化（~3-4 小時）

> 目標：補齊管理平台必要功能

| # | 任務 | 說明 |
|---|------|------|
| 2.1 | **新增「手動新增考題」頁面** | 完整表單 (題文/選項/答案/詳解/來源/難度/知識點) |
| 2.2 | **新增「編輯考題」功能** | 從題庫管理頁面進入完整編輯器 |
| 2.3 | **接上搜尋功能** | 題庫管理頁面加搜尋框，用 FTS5 |
| 2.4 | **加分頁 + 排序** | 題庫管理頁面 |
| 2.5 | **接上驗證功能** | 題庫管理中可標記驗證/顯示驗證狀態 |
| 2.6 | **接上審計記錄** | 每題展開可查看修改歷史 |
| 2.7 | **考卷組裝 UI** | 手選或自動選題，預覽，基礎匯出 |
| 2.8 | **美化首頁儀表板** | 統計卡片 + 圖表 |

### Phase 3：Exam MCP 強化（~2-3 小時）

> 目標：讓任何 Agent 都能正確使用

| # | 任務 | 說明 |
|---|------|------|
| 3.1 | 新增 `exam_get_generation_guide` 工具 | 返回出題指引 + 流程 + JSON Schema |
| 3.2 | 新增 `exam_get_topics` 工具 | 返回知識點列表 + 統計 |
| 3.3 | 新增 `exam_get_question_template` 工具 | 返回題目 JSON Schema |
| 3.4 | 新增 `exam_bulk_save` 工具 | 批次儲存 |
| 3.5 | 新增 `exam_check_duplicate` 工具 | 相似度檢查 |
| 3.6 | 撰寫 Agent 使用文件 | MCP_USAGE.md |
| 3.7 | 提供各 Agent 的設定範例 | Copilot / Claude / Codex 等 |
| 3.8 | 更新 .github/copilot-instructions.md | 加入 MCP 使用指引 |

### Phase 4：整合測試（~1-2 小時）

| # | 任務 | 說明 |
|---|------|------|
| 4.1 | Web App 端到端測試 | 新增/編輯/練習/統計 |
| 4.2 | MCP 工具測試 | 每個工具的 unit test |
| 4.3 | 用 GitHub Copilot Agent Mode 測試出題 | 真實場景驗證 |
| 4.4 | 用 Claude Code 測試出題 | 真實場景驗證 |

---

## 六、目錄結構（重構後）

```
anesthesia-exam/
├── src/
│   ├── domain/                    # 🏛️ 核心領域（不變）
│   │   ├── entities/
│   │   ├── repositories/
│   │   └── value_objects/
│   │
│   ├── application/               # 📋 應用層（新增 Services）
│   │   └── services/
│   │       ├── question_service.py     # 題目 CRUD 封裝
│   │       ├── exam_service.py         # 考卷組裝邏輯
│   │       └── statistics_service.py   # 統計查詢
│   │
│   ├── infrastructure/            # 🔧 基礎設施
│   │   ├── persistence/           # SQLite (不變)
│   │   │   ├── sqlite_repository.py
│   │   │   └── database.py
│   │   ├── mcp/                   # MCP Server (強化)
│   │   │   ├── exam_server.py     # 13 + N 工具
│   │   │   ├── tools/             # 工具拆分
│   │   │   │   ├── crud_tools.py
│   │   │   │   ├── query_tools.py
│   │   │   │   ├── validation_tools.py
│   │   │   │   └── guide_tools.py      # 🆕 出題指引
│   │   │   └── templates/
│   │   │       └── generation_guide.md  # 🆕 出題指引模板
│   │   └── export/                # 🆕 匯出
│   │       └── pdf_exporter.py
│   │
│   └── presentation/             # 🖥️ 呈現層
│       └── streamlit/
│           ├── app.py            # 主程式（精簡後）
│           ├── pages/            # 🆕 Streamlit 多頁面
│           │   ├── 01_dashboard.py
│           │   ├── 02_question_bank.py
│           │   ├── 03_add_question.py
│           │   ├── 04_exam_builder.py
│           │   ├── 05_practice.py
│           │   └── 06_statistics.py
│           └── components/       # 🆕 可復用元件
│               ├── question_card.py
│               ├── question_form.py
│               ├── source_editor.py
│               └── stats_widgets.py
│
├── libs/
│   └── asset-aware-mcp/          # 文獻解析 MCP（不變）
│
├── data/
│   ├── exam.db                   # 共用 SQLite 資料庫
│   ├── sources/                  # 上傳的 PDF
│   └── exams/                    # 匯出的考卷
│
├── docs/
│   └── MCP_USAGE.md              # 🆕 Agent 使用指南
│
├── crush.json                    # Crush MCP 設定
├── opencode.json                 # OpenCode MCP 設定
├── .vscode/mcp.json              # 🆕 VS Code Copilot MCP 設定
└── pyproject.toml
```

---

## 七、資料流對比

### Before（目前）

```
使用者 → Streamlit → Agent Provider → CLI subprocess
         ↕ (混合)      ↕ (嵌入)         ↕ (進程管理)
       UI 更新      Prompt 建構      MCP 工具呼叫
                       ↕                   ↕
                    結果解析 ←──────── exam_save_question
                       ↕
                    SQLite ← 直接存取
```
**問題**：Agent 生命週期由 Web App 管理，緊耦合

### After（重構後）

```
路線 A: Agent 出題
─────────────────
Agent (任意) → exam MCP → SQLite
     ↓
     → asset-aware MCP → RAG 查詢
     ↓
     → exam_save_question → SQLite


路線 B: 手動管理
─────────────────
使用者 → Web App → SQLite (直接讀寫)


路線 C: 練習考試
─────────────────
考生 → Web App → SQLite (讀取) → 作答 → 批改
```
**優點**：Agent 和 Web App 完全獨立，只共用 SQLite

---

## 八、遷移策略

### 不破壞原則

1. **SQLite Schema 不變** — 現有題庫資料完整保留
2. **Domain Layer 不變** — 實體和介面不動
3. **MCP 工具保持向後相容** — 只增不改
4. **Git 分支策略** — 在 `feat/restructure` 分支操作

### 優先級排序（建議執行順序）

```
🔴 Phase 1 (解耦) → 立即可得到乾淨的管理 App
                     ↓
🔴 Phase 3.1-3.3  → Agent 能正確使用 MCP 出題
                     ↓
🟡 Phase 2.1-2.4  → 補齊手動管理功能
                     ↓
🟡 Phase 3.4-3.8  → MCP 進階功能 + 文件
                     ↓
🟢 Phase 2.5-2.8  → 美化 + 進階功能
                     ↓
🟢 Phase 4        → 整合測試
```

---

## 九、決策點（需要你的確認）

| # | 決策 | 選項 | 建議 |
|---|------|------|------|
| **D1** | Web App 框架 | A) 維持 Streamlit<br>B) 改 FastAPI+Jinja2<br>C) FastAPI+React | **A**（先快後好） |
| **D2** | Streamlit 頁面架構 | A) 單檔 app.py<br>B) 多頁面 pages/ 架構 | **B**（更好維護） |
| **D3** | Agent 相關程式碼 | A) 完全刪除<br>B) 移到獨立資料夾存檔 | **A**（Git 有記錄） |
| **D4** | Application Service 層 | A) 現在建立<br>B) 之後再說 | **A**（Phase 2 需要） |
| **D5** | 要不要加 REST API | A) 不加（Streamlit 直連 SQLite）<br>B) 加 FastAPI API 層 | **A 先，B 後** |
| **D6** | MCP 新工具的優先級 | 照 Phase 3 順序 | 確認 |

---

## 十、預期成果

### 重構完成後：

1. **Web App** — 一個乾淨的考題管理 + 作答練習平台，任何人可直接使用
2. **Exam MCP** — 一個文件完善的 MCP Server，任何 Agent 可即插即用
3. **asset-aware MCP** — 已完成，不需變動
4. **出題流程** — Agent 透過兩個 MCP (exam + asset-aware) 完成全流程
5. **管理流程** — 使用者透過 Web App 管理/練習/匯出

### 團隊/個人工作流：

```
日常使用:
1. 開啟 Web App → 瀏覽題庫、作答練習
2. 用 GitHub Copilot → 「幫我從 Miller's Ch.15 出 5 題 propofol 的選擇題」
3. Copilot 調用 exam MCP + asset-aware MCP → 自動生成 + 儲存
4. 回到 Web App → 審閱、驗證、組卷、匯出 PDF
```
