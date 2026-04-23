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

from src.infrastructure.logging import bootstrap_logging, bind_log_context, new_run_id


def main():
    """啟動 Streamlit 應用程式"""
    project_dir = Path(__file__).resolve().parent
    app_path = project_dir / "src" / "presentation" / "streamlit" / "app.py"
    run_id = new_run_id("cli")
    logger = bootstrap_logging(__name__, extra_context={"run_id": run_id, "provider": "streamlit"})
    bind_log_context(entrypoint="main.py")

    if not app_path.exists():
        logger.error("streamlit_app_missing", app_path=str(app_path))
        sys.exit(1)

    logger.info("streamlit_launcher_start", app_path=str(app_path), project_dir=str(project_dir))
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
    logger.info("streamlit_launcher_exit", returncode=result.returncode)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
