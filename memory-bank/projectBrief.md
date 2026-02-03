# Project Brief

## 專案名稱
智慧考卷生成系統 (Anesthesia Exam Generator)

## Purpose
建立一個 Web 應用程式，讓醫學專科考試考生（首重台灣麻醉專科考試）可以：
1. **自動產生考卷** - 符合實際考試規格的模擬考卷
2. **線上作答練習** - 產生考卷後直接在系統上寫題
3. **PDF 下載** - 下載考卷 + 詳解 PDF
4. **獲得詳細解答** - 含精確來源追蹤（頁碼、行號、原文）
5. **互動式學習** - 類似 NotebookLM 的 AI 問答

## Target Users
- 台灣麻醉專科考試考生
- 醫學專科考生

## 核心特色
- **Agent 驅動** - 使用 OpenCode（支援 Skill + Instruction + Sub-agent）
- **精準來源追蹤** - 詳解標註頁碼、行數、原文引用
- **半編碼 Instruction** - 預設模板 + 後台結構化設定可調整
- **多媒體支援** - 支援從教材擷取圖片出題

## 技術選型
| 層次 | 選擇 |
|------|------|
| Agent | OpenCode (Go binary) |
| 前端 UI | Streamlit |
| 後端邏輯 | Open Notebook 複用 |
| PDF 解析 | asset-aware-mcp |
| Python 管理 | uv |
