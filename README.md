# 智慧考卷生成系統 (Anesthesia Exam Generator)

> AI Agent 驅動的醫學專科考試模擬系統

## 功能特色

- 🎯 **自動產生考卷** - 符合實際考試規格的模擬考卷
- ✍️ **線上作答練習** - 產生考卷後直接線上作答
- 📥 **PDF 下載** - 下載考卷 + 詳解 PDF
- 📚 **詳細解答** - 精確來源追蹤（頁碼、行號、原文）
- 💬 **互動式學習** - Crush Agent 即時問答

## 系統架構

```
┌──────────────────┬─────────────────────────────┬────────────────────────────┐
│     Sidebar      │        Main Area            │       Right Panel          │
│  ─ 功能切換      │  ─ 考題作答區               │  ─ Crush 對話區            │
│  ─ 出題設定      │  ─ 對答案/詳解區            │  ─ 即時問答互動            │
└──────────────────┴─────────────────────────────┴────────────────────────────┘
```

### 題目來源

| 來源類型 | 說明 |
| -------- | ---- |
| **Streaming** | Crush Agent 即時流式生成 |
| **Batch** | 題庫批次取得 |

## 技術架構

| 層次 | 技術選型 |
| ---- | -------- |
| Agent | Crush (Go binary) + Claude Skills |
| 前端 UI | Streamlit (三欄式佈局) |
| MCP Server | exam-generator (4 tools) |
| PDF 解析 | asset-aware-mcp |
| Python 管理 | uv |

### Skills 架構 (35 個)

```
.claude/skills/
├── 主編排器: exam-orchestrator
├── 知識處理層: knowledge-indexer, scope-analyzer, knowledge-extractor
├── 出題生成層: mcq-generator, essay-generator, question-set-generator, image-question-generator
├── 品質控制層: question-validator, difficulty-classifier, duplicate-checker, source-tracker
├── 考古題層: past-exam-analyzer, past-exam-matcher
├── 輸出層: explanation-generator, exam-assembler, export-formatter
└── 開發工具: git-precommit, code-reviewer, memory-updater, ...
```

## 快速開始

```bash
# 建立虛擬環境
uv venv
uv sync

# 啟動應用
uv run streamlit run main.py
```

### Crush Agent 設定

```bash
# 設定 crush.json
{
  "skills_paths": [".claude/skills"],
  "mcpServers": {
    "exam-generator": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.infrastructure.mcp.exam_server"]
    }
  }
}
```

## 大型 PDF 處理

針對大型教材 (如 Miller's Anesthesia 9th, ~3500 頁)：

1. **分批解析** - 每次處理 50-100 頁
2. **斷點續傳** - 支援暫停/繼續
3. **原子化切分** - 保留頁碼、行號
4. **向量索引** - Chroma / pgvector

## 文檔

| 文件 | 說明 |
| ---- | ---- |
| [SPEC.md](SPEC.md) | 完整規格書 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架構設計 |
| [CHANGELOG.md](CHANGELOG.md) | 變更記錄 |
| [ROADMAP.md](ROADMAP.md) | 開發路線圖 |
| [CONSTITUTION.md](CONSTITUTION.md) | 專案最高原則 |

## Memory Bank

跨對話的專案記憶系統：

| 文件 | 用途 |
| ---- | ---- |
| `memory-bank/activeContext.md` | 當前工作焦點 |
| `memory-bank/progress.md` | 進度追蹤 |
| `memory-bank/decisionLog.md` | 決策記錄 |

## 授權

MIT License
