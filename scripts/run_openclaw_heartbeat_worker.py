#!/usr/bin/env python
"""Run one OpenClaw backlog worker pass."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.openclaw_backlog_worker import OpenClawBacklogWorker
from src.application.services.telegram_admin_service import TelegramNotifier
from src.infrastructure.agent.provider import AgentProviderConfig, create_agent_provider
from src.infrastructure.logging import bootstrap_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the anesthesia-exam OpenClaw backlog worker once.")
    parser.add_argument("--max-jobs", type=int, default=1, help="Maximum pending jobs to process in this pass.")
    parser.add_argument(
        "--heartbeat-max-requests",
        type=int,
        default=5,
        help="Maximum heartbeat jobs to create before processing pending jobs.",
    )
    parser.add_argument("--no-generate-jobs", action="store_true", help="Skip heartbeat job generation.")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and list work without dispatching OpenClaw.")
    parser.add_argument(
        "--process-auto-coverage",
        action="store_true",
        help="Allow processing heartbeat jobs without source_request_id. Default skips them for safety.",
    )
    parser.add_argument("--provider", default="openclaw", help="Agent provider name. Defaults to openclaw.")
    parser.add_argument("--model", default=None, help="Optional model override.")
    parser.add_argument("--no-telegram", action="store_true", help="Do not send Telegram admin notification.")
    return parser.parse_args()


def build_provider(args: argparse.Namespace):
    config = AgentProviderConfig.load(
        project_dir=PROJECT_ROOT,
        crush_config_path=PROJECT_ROOT / "crush.json",
        provider_override=args.provider,
        model_override=args.model,
    )
    provider = create_agent_provider(config)
    if not args.dry_run:
        available, reason = provider.is_available()
        if not available:
            raise RuntimeError(f"Agent provider unavailable: {reason}")
    return provider


def main() -> int:
    bootstrap_logging("openclaw-backlog-worker")
    args = parse_args()
    provider = build_provider(args)
    result = OpenClawBacklogWorker().run_once(
        provider=provider,
        max_jobs=args.max_jobs,
        heartbeat_max_requests=args.heartbeat_max_requests,
        generate_jobs=not args.no_generate_jobs,
        dry_run=args.dry_run,
        process_auto_jobs=args.process_auto_coverage,
    )
    payload = result.to_dict()
    if not args.no_telegram:
        TelegramNotifier.from_env().send_worker_result(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
