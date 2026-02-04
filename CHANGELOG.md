# Changelog

所有重要變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)，
專案遵循 [語義化版本](https://semver.org/lang/zh-TW/)。

## [Unreleased]

### Added

- SQLite 資料庫架構 (`data/questions.db`)
  - questions 表：完整題目儲存
  - question_audits 表：操作審計追蹤
  - FTS5 全文搜尋支援
- Repository Pattern 實作
  - `IQuestionRepository` 介面 (DDD)
  - `SQLiteQuestionRepository` 實作
- Audit 追蹤機制
  - `AuditAction`: CREATED, UPDATED, VALIDATED, REJECTED, DELETED, RESTORED
  - `ActorType`: AGENT, SKILL, USER, SYSTEM
  - `AuditEntry`, `GenerationContext` 值物件
- MCP Server 擴展為 13 個工具
  - 新增：update_question, get_audit_log, mark_validated, search, restore_question
- Question CRUD Skill 文檔 (`.claude/skills/question-crud/`)
- Streamlit 三欄佈局
  - 左：側邊選單 + 題庫概況
  - 中：操作區 (考題生成/作答練習/題庫管理/統計)
  - 右：常駐 AI Chat
- Port 8501 標準化 (`.github/bylaws/streamlit-port.md`)
- JSON → SQLite 資料遷移腳本

### Changed

- MCP Server 從 JSON 檔案儲存改為 SQLite Repository
- Streamlit UI 從單頁切換改為三欄佈局

### Known Issues

- ⚠️ 來源追蹤是 AI 編造的假資料，尚未串接 PDF 解析工具
- 需要 asset-aware-mcp 或類似工具來實現真正的來源追蹤

## [0.1.0] - 2025-12-15

### Added

- 初始化專案結構
- 新增 Claude Skills 支援
  - `git-doc-updater` - Git 提交前自動更新文檔技能
- 新增 Memory Bank 系統
  - `activeContext.md` - 當前工作焦點
  - `productContext.md` - 專案上下文
  - `progress.md` - 進度追蹤
  - `decisionLog.md` - 決策記錄
  - `projectBrief.md` - 專案簡介
  - `systemPatterns.md` - 系統模式
  - `architect.md` - 架構文檔
- 新增 VS Code 設定
  - 啟用 Claude Skills
  - 啟用 Agent 模式
  - 啟用自定義指令檔案
