# Copilot 自定義指令

此文件為 VS Code GitHub Copilot 及 Claude Code 提供專案上下文與操作規範。

---

## 專案概述

這是 **智慧考卷生成系統 (Anesthesia Exam Generator)**，整合了：

- AI Agent 驅動的考題生成（Crush + MCP）
- 精準來源追蹤（頁碼、行號、原文）
- 線上作答練習 + PDF 下載
- DDD + DAL 獨立架構
- 憲法-子法層級規則系統
- Claude Skills 模組化技能
- Memory Bank 專案記憶
- 流式生成即時預覽

### 技術選型

| 層次 | 選擇 |
| ---- | ---- |
| Agent | Crush (Go binary, charm.sh) |
| 前端 UI | Streamlit (port 8501) |
| PDF 解析/RAG | asset-aware-mcp (LightRAG) |
| 題庫管理 | exam-generator MCP + SQLite |
| Python 管理 | uv |

### MCP Server 架構

```
crush.json
├── exam-generator     # 考題 CRUD (13 個工具)
│   ├── exam_save_question
│   ├── exam_list_questions
│   ├── exam_get_question
│   ├── exam_update_question
│   ├── exam_delete_question
│   ├── exam_restore_question
│   ├── exam_validate_question
│   ├── exam_mark_validated
│   ├── exam_get_audit_log
│   ├── exam_search
│   ├── exam_create_exam
│   └── exam_get_stats
│
└── asset-aware        # PDF 解析與 RAG
    ├── ingest_documents          # 處理 PDF → 建立索引
    ├── parse_pdf_structure       # 高精度結構解析 (Marker)
    ├── consult_knowledge_graph   # RAG 查詢
    ├── search_source_location    # 🔥 精確定位來源（頁碼+bbox+snippet）
    ├── get_section_content       # 讀取特定章節
    ├── fetch_document_asset      # 取得表格/圖片/章節
    └── list_documents            # 列出已處理文件
```

---

## 開發哲學 💡

> **「想要寫文件的時候，就更新 Memory Bank 吧！」**
>
> **「想要零散測試的時候，就寫測試檔案進 tests/ 資料夾吧！」**

- 不要另開檔案寫筆記，直接寫進 Memory Bank
- 今天的零散測試，就是明天的回歸測試

---

## 法規層級

```
CONSTITUTION.md          ← 最高原則（不可違反）
  │
  ├── .github/bylaws/    ← 子法（細則規範）
  │     ├── ddd-architecture.md
  │     ├── git-workflow.md
  │     ├── python-environment.md
  │     └── memory-bank.md
  │
  └── .claude/skills/    ← 實施細則（操作程序）
```

你必須遵守以下法規層級：

1. **憲法**：`CONSTITUTION.md` - 最高原則，不可違反
2. **子法**：`.github/bylaws/*.md` - 細則規範
3. **技能**：`.claude/skills/*/SKILL.md` - 操作程序

---

## 架構原則

### DDD (Domain-Driven Design)

- **Domain Layer 不依賴外部**
- **DAL (Data Access Layer) 必須獨立**
- 使用 Repository Pattern
- 依賴方向：`Presentation → Application → Domain ← Infrastructure`

詳見：`.github/bylaws/ddd-architecture.md`

### 目錄結構約定

```
src/
├── Domain/           # 核心領域（無外部依賴）
├── Application/      # 應用層（用例編排）
├── Infrastructure/   # 基礎設施（DAL、外部服務）
└── Presentation/     # 呈現層（API、CLI）
```

---

## Python 環境（uv 優先）

- **優先使用 uv** 管理套件和虛擬環境
- 新專案必須建立 `pyproject.toml` + `uv.lock`
- 禁止全域安裝套件

```bash
# 初始化環境
uv venv
uv sync --all-extras

# 安裝依賴
uv add package-name
uv add --dev pytest ruff mypy bandit vulture
```

詳見：`.github/bylaws/python-environment.md`

---

## 🚨 出題流程（重要！）

### 正確流程（先查詢再出題）

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: 建立知識庫（一次性）                                  │
├─────────────────────────────────────────────────────────────┤
│ 用戶上傳 PDF → ingest_documents() → 建立 RAG 索引           │
│ 返回 doc_id: "a1b2c3d4"                                      │
└─────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: 出題（查詢真實來源）                                  │
├─────────────────────────────────────────────────────────────┤
│ 1. consult_knowledge_graph("propofol pharmacology")         │
│    → 取得相關知識內容                                         │
│                                                              │
│ 2. search_source_location(doc_id, "GABA-A")                 │
│    → 取得精確來源 (page, bbox, snippet)                      │
│                                                              │
│ 3. 根據真實內容生成題目                                        │
│                                                              │
│ 4. exam_save_question(題目 + 真實來源)                       │
└─────────────────────────────────────────────────────────────┘
```

### ⚠️ 錯誤流程（會產生幻覺）

```
❌ 用戶: "出 5 題選擇題"
❌ Agent: 從記憶中編造題目 + 編造來源
❌ exam_save_question: 儲存（來源是假的！）
```

**重要原則：Agent 沒有查詢知識庫就出題 = 必然產生幻覺**

---

## Memory Bank 同步

每次重要操作必須更新 Memory Bank：

| 操作 | 更新文件 |
| ---- | -------- |
| 完成任務 | `progress.md` (Done) |
| 開始任務 | `progress.md` (Doing), `activeContext.md` |
| 重大決策 | `decisionLog.md` |
| 架構變更 | `architect.md` |

詳見：`.github/bylaws/memory-bank.md`

---

## Git 工作流

提交前必須執行檢查清單：

1. ✅ Memory Bank 同步（必要）
2. 📖 README 更新（如需要）
3. 📋 CHANGELOG 更新（如需要）
4. 🗺️ ROADMAP 標記（如需要）

詳見：`.github/bylaws/git-workflow.md`

---

## 可用 Skills

位於 `.claude/skills/` 目錄：

### 核心技能

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **git-precommit** | Git 提交前編排器 | GIT, gc, commit, push, 提交, 推送 |
| **ddd-architect** | DDD 架構輔助（前後端） | DDD, arch, 架構, 新功能, scaffold |
| **code-refactor** | 主動重構與模組化 | RF, refactor, 重構, 拆分, 模組化 |
| **code-reviewer** | 程式碼審查 | CR, review, 審查, 檢查, PR |
| **test-generator** | 測試生成 + 靜態分析 | TG, test, 測試, coverage, pytest |
| **security-reviewer** | 安全性審查 (OWASP) | SEC, security, 安全, OWASP, 漏洞 |

### 記憶管理

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **memory-updater** | Memory Bank 同步 | MB, memory, 記憶, 進度, 更新記憶 |
| **memory-checkpoint** | 記憶檢查點 | CP, checkpoint, 存檔, 保存, dump |

### 文檔管理

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **readme-updater** | README 智能更新 | readme, 說明, 文檔同步 |
| **readme-i18n** | 多語言 README | i18n, 翻譯, 多語言, bilingual |
| **changelog-updater** | CHANGELOG 更新 | CL, changelog, 變更, 版本 |
| **roadmap-updater** | ROADMAP 狀態追蹤 | RM, roadmap, 路線, 里程碑 |
| **git-doc-updater** | Git 提交前文檔檢查 | docs, 文檔, sync docs, release |

### 專案管理

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **project-init** | 專案初始化 | init, new, 新專案, bootstrap |
| **skill-generator** | 生成新 Skill | SG, new skill, 建立技能 |

### 工作流 Skills（組合多個 Skills）

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **feature-development** | 完整功能開發流程 | FD, 新功能, 開發功能, feature |
| **bug-fix** | 結構化 Bug 修復 | BF, 修 bug, fix bug, debug |
| **code-review-workflow** | 完整程式碼審查 | PRW, 審查流程, review workflow |
| **release** | 版本發布準備 | REL, release, 發布, 版本發布 |

### 考試生成 Skills（核心業務）

#### 主編排器

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **exam-orchestrator** | 完整出題流程編排 | 生成考卷, 出考題, 模擬考, generate exam |

#### 知識處理層

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **knowledge-indexer** | PDF 解析與 RAG 索引 | 索引教材, 解析 PDF, index, parse pdf |
| **scope-analyzer** | 範圍分析與主題權重 | 分析範圍, 範圍分析, scope |
| **knowledge-extractor** | 概念抽取與知識圖譜 | 抽取概念, 知識抽取, knowledge graph |

#### 出題生成層

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **mcq-generator** | 選擇題生成 | 選擇題, 單選題, MCQ, multiple choice |
| **essay-generator** | 問答題/申論題生成 | 問答題, 申論題, essay, short answer |
| **question-set-generator** | 題組題生成 | 題組, 情境題, 病例題, question set |
| **image-question-generator** | 圖片題生成 | 圖片題, 心電圖題, 影像題, image question |

#### 品質控制層

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **question-validator** | 題目驗證 | 驗證題目, 檢查題目, validate, QA |
| **difficulty-classifier** | 難度分類 (Ragas) | 難度分類, difficulty, 評估難度 |
| **duplicate-checker** | 重複題目檢查 | 查重, 重複檢查, duplicate, 相似題 |
| **source-tracker** | 來源追蹤與驗證 | 來源追蹤, 出處, source, citation |

#### 考古題層

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **past-exam-analyzer** | 考古題分析 | 考古題分析, 歷屆考題, past exam |
| **past-exam-matcher** | 考古題比對 | 考古題比對, 類似考古題, match past |

#### 輸出層

| Skill | 用途 | 觸發詞 |
| ----- | ---- | ------ |
| **explanation-generator** | 詳解生成 | 詳解, 解答, explanation, 解析 |
| **exam-assembler** | 試卷組裝 | 組卷, 組裝試卷, assemble, 產生試卷 |
| **export-formatter** | 匯出格式 | 匯出, export, PDF, Word, 列印 |

---

## 💸 Memory Checkpoint 規則

為避免對話被 Summarize 壓縮時遺失重要上下文：

### 主動觸發時機

1. 對話超過 **10 輪**
2. 累積修改超過 **5 個檔案**
3. 完成一個 **重要功能/修復**
4. 使用者說要 **離開/等等**

### 執行指令

- 「記憶檢查點」「checkpoint」「存檔」
- 「保存記憶」「sync memory」

### 必須記錄

- 當前工作焦點
- 變更的檔案列表（完整路徑）
- 待解決事項
- 下一步計畫

---

## 常用指令

### 啟動服務

```bash
# 安裝 Web 依賴
uv sync --extra webapp --dev

# 啟動 Streamlit Web (port 8501)
./scripts/run_web.sh

# 或使用 Python 入口
uv run python main.py

# 安裝 / 啟用 systemd service
./scripts/install_systemd_service.sh

# 檢查 service 狀態
systemctl status anesthesia-exam-web.service --no-pager
```

### 開發相關

```
「啟動 streamlit」    → 啟動 Web 介面 (port 8501)
「準備 commit」       → 執行完整提交流程
「快速 commit」       → 只同步 Memory Bank
「建立新功能 X」      → 生成 DDD 結構
「review 程式碼」     → 程式碼審查
「更新 memory bank」  → 同步專案記憶
「checkpoint」        → 記憶檢查點
「新功能開發」        → 完整功能開發流程
「修 bug」            → 結構化 Bug 修復
```

### 考試生成相關

```
「生成考卷」          → 執行完整出題流程
「出 10 題選擇題」    → 選擇題生成
「分析範圍」          → 範圍與主題分析
「驗證題目」          → 品質檢查
「比對考古題」        → 考古題相似度比對
「生成詳解」          → 答案解析生成
「組裝試卷」          → 組合成完整試卷
「匯出 PDF」          → 匯出為 PDF 格式
```

---

## 回應風格

- 使用**繁體中文**
- 提供清晰的步驟說明
- 引用相關法規條文
- 執行操作後更新 Memory Bank

---

## 注意事項

- 修改程式碼前先更新規格文檔
- 程式碼是文檔的「編譯產物」
- 遵循 Conventional Commits 格式
- 採用 DDD 架構
