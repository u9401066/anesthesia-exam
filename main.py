"""
智慧考卷生成系統 - 入口點

Usage:
    ./scripts/run_web.sh
    或
    python main.py
"""

import subprocess
import sys
from pathlib import Path


def main():
    """啟動 Streamlit 應用程式"""
    project_dir = Path(__file__).resolve().parent
    app_path = project_dir / "src" / "presentation" / "streamlit" / "app.py"

    if not app_path.exists():
        print(f"錯誤: 找不到 {app_path}")
        sys.exit(1)

    print("🚀 啟動考卷生成系統...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.port",
            "8501",
            "--server.address",
            "0.0.0.0",
            "--server.headless=true",
        ],
        cwd=str(project_dir),
        check=False,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
