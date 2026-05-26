#!/usr/bin/env python
"""Send one Telegram admin status report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.telegram_admin_service import TelegramAdminStatusService, TelegramNotifier
from src.infrastructure.logging import bootstrap_logging


def main() -> int:
    bootstrap_logging("telegram-status-report")
    notifier = TelegramNotifier.from_env()
    sent = notifier.send_status_report(TelegramAdminStatusService(project_dir=PROJECT_ROOT))
    print(json.dumps({"sent": sent, "configured": notifier.config.is_configured}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
