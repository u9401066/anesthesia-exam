#!/usr/bin/env python3
"""
Heartbeat CLI - 掃描題庫缺口並產生 Job 檔案

用法：
    # 只分析缺口（不寫 job 檔）
    uv run python scripts/run_heartbeat.py --dry-run

    # 產生 job 檔案到 data/jobs/
    uv run python scripts/run_heartbeat.py --max-requests 3

    # 顯示目前狀態摘要
    uv run python scripts/run_heartbeat.py --status

    # 列出所有 pending / done / error job
    uv run python scripts/run_heartbeat.py --list-jobs
    uv run python scripts/run_heartbeat.py --list-jobs --job-status done

    # 標記 job 完成（Agent 執行後手動回報）
    uv run python scripts/run_heartbeat.py --complete data/jobs/heartbeat_xxx.json --generated 5

Agent 工作流程：
    1. run_heartbeat.py             → 寫 pending job 到 data/jobs/
    2. Agent (Crush/OpenCode) 讀取  → 照 prompt 出題
    3. run_heartbeat.py --complete  → 標記完成 + 更新 scope_request
"""

import argparse
import json
import sys
from pathlib import Path

# 確保專案根目錄在 Python path
PROJECT_DIR = Path(__file__).parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.application.services.heartbeat_service import HeartbeatService


def main():
    parser = argparse.ArgumentParser(description="Heartbeat 題庫補充 - Job 檔案模式")
    parser.add_argument("--dry-run", action="store_true", help="只分析缺口，不寫 job 檔案")
    parser.add_argument("--status", action="store_true", help="顯示狀態摘要")
    parser.add_argument("--max-requests", type=int, default=5, help="單次最多產生幾筆 job")
    parser.add_argument("--list-jobs", action="store_true", help="列出 job 檔案")
    parser.add_argument("--job-status", choices=["pending", "done", "error"], help="篩選 job 狀態（搭配 --list-jobs）")
    parser.add_argument("--complete", metavar="JOB_PATH", help="標記某 job 完成")
    parser.add_argument("--generated", type=int, default=0, help="完成時回報生成題數（搭配 --complete）")
    parser.add_argument("--error", metavar="JOB_PATH", help="標記某 job 失敗")
    parser.add_argument("--error-msg", default="unknown error", help="失敗訊息（搭配 --error）")
    args = parser.parse_args()

    service = HeartbeatService()

    # --- 狀態摘要 ---
    if args.status:
        summary = service.get_status_summary()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # --- 列出 jobs ---
    if args.list_jobs:
        jobs = service.list_jobs(status=args.job_status)
        if not jobs:
            print("（沒有符合條件的 job）")
            return
        for j in jobs:
            status_icon = {"pending": "⏳", "done": "✅", "error": "❌"}.get(j["status"], "❓")
            print(f"  {status_icon} [{j['status']}] {j['topic']} (缺 {j['deficit']} 題) → {j.get('_path', '')}")
        print(f"\n共 {len(jobs)} 筆")
        return

    # --- 標記完成 ---
    if args.complete:
        service.mark_job_done(args.complete, questions_generated=args.generated)
        print(f"✅ 已標記完成：{args.complete}（生成 {args.generated} 題）")
        return

    # --- 標記失敗 ---
    if args.error:
        service.mark_job_error(args.error, args.error_msg)
        print(f"❌ 已標記失敗：{args.error}")
        return

    # --- 主流程：掃描缺口 → 寫 job 檔 ---
    result = service.run_heartbeat(
        max_requests=args.max_requests,
        dry_run=args.dry_run,
    )

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

    if result.job_paths:
        print(f"\n📝 已寫入 {len(result.job_paths)} 個 job 檔案：")
        for p in result.job_paths:
            print(f"  → {p}")
        print("\n💡 Agent 可讀取上述檔案中的 prompt 來出題。")

    if result.errors:
        print(f"\n⚠️  {len(result.errors)} 個錯誤：", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
