# Product Context

Describe the product.

## Overview

Provide a high-level overview of the project.

## Core Features

- Streamlit 工作台：教材索引、AI 出題、題庫管理、作答練習、右側常駐 AI 助手
- 題庫治理：管理者審查、`validated_only` 篩選、`exam_track` 題目分類
- Backlog 補題工作流：使用者可提交 `scope request`，heartbeat 會產出外部 agent 可讀的 job 檔
- 考古題後台流程：past-exam extraction / classification / blueprint / pipeline harness

## Technical Stack

- Python + Streamlit
- SQLite Repository + Audit Trail
- MCP servers: exam-generator / asset-aware
- Agent providers: Crush / OpenCode / Copilot SDK

## Project Description

智慧考卷生成系統，透過 Crush Agent 與 MCP 工具鏈產生麻醉學題目，支援即時流式預覽、題庫管理、作答練習與來源追蹤。



## Architecture

採 DDD 分層（presentation/application/domain/infrastructure）。Streamlit 為前端入口，Crush CLI 進行 AI 生成，exam-generator MCP 負責題目 CRUD，SQLite Repository 提供持久化與審計。



## Technologies

- Python
- Streamlit
- SQLite
- MCP
- Crush CLI
- uv



## Libraries and Dependencies

- streamlit
- mcp
- sqlite3
- dataclasses
- pathlib
- structlog
- pydantic

