"""
智慧考卷生成系統 - 入口點

Usage:
    uv run streamlit run src/presentation/streamlit/app.py
    或
    python main.py (直接啟動 Streamlit)
"""

import subprocess
import sys
from pathlib import Path


def main():
    """啟動 Streamlit 應用程式"""
    app_path = Path(__file__).parent / "src" / "presentation" / "streamlit" / "app.py"
    
    if not app_path.exists():
        print(f"錯誤: 找不到 {app_path}")
        sys.exit(1)
    
    print("🚀 啟動考卷生成系統...")
    subprocess.run(["streamlit", "run", str(app_path)])


if __name__ == "__main__":
    main()
