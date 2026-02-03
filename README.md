# 智慧考卷生成系統 (Anesthesia Exam Generator)

> AI 驅動的醫學專科考試模擬系統

## 功能特色

- 🎯 **自動產生考卷** - 符合實際考試規格的模擬考卷
- ✍️ **線上作答練習** - 產生考卷後直接線上作答
- 📥 **PDF 下載** - 下載考卷 + 詳解 PDF
- 📚 **詳細解答** - 精確來源追蹤（頁碼、行號、原文）
- 💬 **互動式學習** - 類似 NotebookLM 的 AI 問答

## 技術架構

| 層次 | 技術選型 |
| ---- | -------- |
| Agent | OpenCode (Go binary) |
| 前端 UI | Streamlit |
| 後端邏輯 | Open Notebook 複用 |
| PDF 解析 | asset-aware-mcp |
| Python 管理 | uv |

## 快速開始

```bash
# 建立虛擬環境
uv venv
uv sync

# 啟動應用
uv run streamlit run main.py
```

## 文檔

- [完整規格書](SPEC.md)
- [架構設計](ARCHITECTURE.md)
- [變更記錄](CHANGELOG.md)
- [開發路線圖](ROADMAP.md)

## 授權

MIT License
