# Streamlit 啟動配置

## 端口規範

**統一使用 8501 端口**

```bash
# 正確啟動方式（推薦）
./scripts/run_web.sh

# 或使用 Python 入口
uv run python main.py

# 部署為 systemd service
./scripts/install_systemd_service.sh
```

## 禁止使用的端口

- ❌ 8500
- ❌ 8502  
- ❌ 8503
- ❌ 8504
- ❌ 8505
- ❌ 其他任何 850x 端口

## 清理殘留進程

如果遇到端口被占用：

```bash
# 查看 8501 是否已有 Streamlit 回應
curl -I http://127.0.0.1:8501

# 停掉舊的 Streamlit 進程（若確認可以安全重啟）
pkill -f "streamlit run src/presentation/streamlit/app.py"
```

## Streamlit 配置

正式部署時優先使用下列檔案，而不是臨時手打一串 CLI 參數：

- `scripts/run_web.sh`
- `deploy/systemd/anesthesia-exam-web.service`
