#!/usr/bin/env python
"""Run the read-only Telegram admin bot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.telegram_admin_service import TelegramAdminBot
from src.infrastructure.logging import bootstrap_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the anesthesia-exam Telegram admin bot.")
    parser.add_argument("--once", action="store_true", help="Poll Telegram once and exit.")
    parser.add_argument("--offset", type=int, default=None, help="Optional Telegram update offset.")
    return parser.parse_args()


def main() -> int:
    bootstrap_logging("telegram-admin-bot")
    args = parse_args()
    bot = TelegramAdminBot.from_env()
    if not bot.config.is_configured:
        print(json.dumps({"configured": False, "message": "Telegram admin bot disabled"}, ensure_ascii=False, indent=2))
        return 0
    if args.once:
        next_offset = bot.poll_once(offset=args.offset)
        print(json.dumps({"configured": True, "next_offset": next_offset}, ensure_ascii=False, indent=2))
        return 0
    bot.poll_forever(offset=args.offset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
