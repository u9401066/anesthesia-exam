# Streamlit 啟動配置

## 端口規範

**統一使用 8501 端口**

```bash
# 正確啟動方式
uv run streamlit run src/presentation/streamlit/app.py --server.port 8501

# 或使用專案腳本
uv run python -m streamlit run src/presentation/streamlit/app.py --server.port 8501
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

```powershell
# 停止所有 Python 進程
Get-Process -Name "python*" -ErrorAction SilentlyContinue | Stop-Process -Force

# 檢查端口狀態
netstat -ano | Select-String "8501"
```

## Streamlit 配置

專案使用 `.streamlit/config.toml` 進行配置（如需要可建立）。
