"""
Heartbeat Service - 背景補題服務

週期性掃描出題需求 backlog，分析題庫覆蓋率缺口，
產生 Job 檔案供 Agent (Crush / OpenCode) 讀取執行。

設計：
  heartbeat → 分析缺口 → 寫 JSON job 到 data/jobs/
  agent（外部）→ 讀取 job → 出題 → 更新 job status

Job 檔案格式：
  data/jobs/heartbeat_{timestamp}_{topic_hash}.json
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.domain.entities.scope_request import ScopeRequestStatus
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository
from src.infrastructure.persistence.sqlite_scope_request_repo import get_scope_request_repository

PROJECT_DIR = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CoverageGap:
    """題庫覆蓋率缺口"""

    topic: str
    current_count: int
    target_count: int
    deficit: int
    difficulty: Optional[str] = None
    exam_track: Optional[str] = None
    source_request_id: Optional[str] = None


@dataclass
class JobFile:
    """一筆要寫入 data/jobs/ 的 job 描述"""

    job_id: str
    path: Path
    gap: CoverageGap
    prompt: str
    status: str = "pending"  # pending → picked → done / error
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "job_type": "question_backfill",
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "topic": self.gap.topic,
            "deficit": self.gap.deficit,
            "difficulty": self.gap.difficulty,
            "exam_track": self.gap.exam_track,
            "source_request_id": self.gap.source_request_id,
            "expected_output": {
                "action": "save_questions_and_mark_complete",
                "complete_with": "python scripts/run_heartbeat.py --complete <job_path> --generated <n>",
            },
            "prompt": self.prompt,
        }


@dataclass
class HeartbeatResult:
    """單次 heartbeat 執行結果"""

    timestamp: str
    gaps_found: int
    jobs_written: int
    job_paths: list[str] = field(default_factory=list)
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "gaps_found": self.gaps_found,
            "jobs_written": self.jobs_written,
            "job_paths": self.job_paths,
            "skipped": self.skipped,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class HeartbeatService:
    """
    背景題庫補充服務

    流程：
    1. 掃描 scope_requests 表中 pending / approved / in_progress 的需求
    2. 比對現有題庫覆蓋率，找出缺口
    3. 產生 Job JSON 檔案寫入 data/jobs/
    4. 外部 Agent 讀取 job 檔 → 出題 → 標記完成
    5. (可選) heartbeat 收工時檢查已完成的 job → 更新 scope_request
    """

    def __init__(self, jobs_dir: Optional[Path] = None):
        self.question_repo = get_question_repository()
        self.scope_repo = get_scope_request_repository()
        self.jobs_dir = jobs_dir or (PROJECT_DIR / "data" / "jobs")
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 分析
    # ------------------------------------------------------------------

    def analyze_coverage_gaps(self) -> list[CoverageGap]:
        """分析題庫覆蓋率缺口（合併 scope requests + 題庫統計）"""
        gaps: list[CoverageGap] = []

        # 1. 從 scope requests 找缺口
        pending = self.scope_repo.get_pending_requests()
        for req in pending:
            deficit = req.target_count - req.fulfilled_count
            if deficit > 0:
                gaps.append(
                    CoverageGap(
                        topic=req.topic,
                        current_count=req.fulfilled_count,
                        target_count=req.target_count,
                        deficit=deficit,
                        difficulty=req.difficulty,
                        exam_track=req.exam_track,
                        source_request_id=req.id,
                    )
                )

        # 2. 從題庫統計找低覆蓋主題
        stats = self.question_repo.get_statistics()
        by_topic = stats.get("by_topic", {})

        # 若某主題題數 < 5 且不在 scope requests 中，自動產生一筆建議
        existing_topics = {req.topic for req in pending}
        for topic_name, count in by_topic.items():
            if count < 5 and topic_name not in existing_topics:
                gaps.append(
                    CoverageGap(
                        topic=topic_name,
                        current_count=count,
                        target_count=5,
                        deficit=5 - count,
                    )
                )

        # 按缺口大小排序
        gaps.sort(key=lambda g: g.deficit, reverse=True)
        return gaps

    # ------------------------------------------------------------------
    # Prompt 建構
    # ------------------------------------------------------------------

    def build_generation_prompt(self, gap: CoverageGap) -> str:
        """根據缺口建立出題 prompt"""
        parts = [
            f"請針對以下主題產生 {gap.deficit} 題選擇題：",
            f"- 主題：{gap.topic}",
        ]

        if gap.difficulty:
            parts.append(f"- 難度：{gap.difficulty}")
        if gap.exam_track:
            parts.append(f"- 考試類型：{gap.exam_track}")

        parts.extend(
            [
                "",
                "請使用 MCP 工具 consult_knowledge_graph 查詢相關知識，",
                "然後用 search_source_location 取得精確來源，",
                "最後用 exam_save_question 將題目存入題庫。",
                "每題必須包含完整來源追蹤（頁碼、原文 snippet）。",
            ]
        )

        if gap.source_request_id:
            parts.append(f"\n（對應需求 ID: {gap.source_request_id}）")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Job I/O
    # ------------------------------------------------------------------

    def _make_job_id(self, gap: CoverageGap, now: datetime) -> str:
        """產生唯一 job id：heartbeat_{timestamp}_{topic_hash8}"""
        ts = now.strftime("%Y%m%d_%H%M%S")
        h = hashlib.sha256(gap.topic.encode()).hexdigest()[:8]
        return f"heartbeat_{ts}_{h}"

    def write_job(self, gap: CoverageGap) -> JobFile:
        """為單一缺口寫入 job 檔案"""
        now = datetime.now()
        job_id = self._make_job_id(gap, now)
        prompt = self.build_generation_prompt(gap)

        job = JobFile(
            job_id=job_id,
            path=self.jobs_dir / f"{job_id}.json",
            gap=gap,
            prompt=prompt,
            status="pending",
            created_at=now.isoformat(),
        )

        job.path.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return job

    def list_jobs(self, status: Optional[str] = None) -> list[dict]:
        """列出 data/jobs/ 下的 job 檔案"""
        jobs = []
        for f in sorted(self.jobs_dir.glob("heartbeat_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if status is None or data.get("status") == status:
                    data["_path"] = str(f)
                    jobs.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return jobs

    def mark_job_done(self, job_path: str | Path, questions_generated: int = 0) -> None:
        """Agent 完成後呼叫：標記 job done + 更新 scope request"""
        p = Path(job_path)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["status"] = "done"
        data["completed_at"] = datetime.now().isoformat()
        data["questions_generated"] = questions_generated
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 更新對應的 scope_request
        req_id = data.get("source_request_id")
        if req_id and questions_generated > 0:
            self.scope_repo.increment_fulfilled(req_id, questions_generated)

    def mark_job_error(self, job_path: str | Path, error_msg: str) -> None:
        """標記 job 失敗"""
        p = Path(job_path)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["status"] = "error"
        data["error"] = error_msg
        data["failed_at"] = datetime.now().isoformat()
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def run_heartbeat(
        self,
        max_requests: int = 5,
        dry_run: bool = False,
    ) -> HeartbeatResult:
        """
        執行一次 heartbeat 掃描 → 產生 job 檔案

        Args:
            max_requests: 單次最多產生幾筆 job
            dry_run: 若 True，只分析不寫檔

        Returns:
            HeartbeatResult
        """
        errors: list[str] = []
        job_paths: list[str] = []
        skipped = 0

        gaps = self.analyze_coverage_gaps()

        if dry_run:
            return HeartbeatResult(
                timestamp=datetime.now().isoformat(),
                gaps_found=len(gaps),
                jobs_written=0,
                skipped=len(gaps),
                errors=["dry_run=True, 未實際寫入 job 檔案"],
            )

        # 檢查是否已有相同 topic 的 pending job，避免重複
        existing_pending = {j["topic"] for j in self.list_jobs(status="pending")}

        for gap in gaps[:max_requests]:
            if gap.topic in existing_pending:
                skipped += 1
                continue

            try:
                # 若有對應 scope request，標記為 in_progress
                if gap.source_request_id:
                    self.scope_repo.update_status(
                        gap.source_request_id,
                        ScopeRequestStatus.IN_PROGRESS,
                    )

                job = self.write_job(gap)
                job_paths.append(str(job.path))

            except Exception as e:
                errors.append(f"Gap '{gap.topic}': {e}")

        return HeartbeatResult(
            timestamp=datetime.now().isoformat(),
            gaps_found=len(gaps),
            jobs_written=len(job_paths),
            job_paths=job_paths,
            skipped=skipped,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # 狀態摘要
    # ------------------------------------------------------------------

    def get_status_summary(self) -> dict:
        """取得 heartbeat 狀態摘要（供 UI 顯示）"""
        gaps = self.analyze_coverage_gaps()
        scope_stats = self.scope_repo.get_statistics()
        question_stats = self.question_repo.get_statistics()

        pending_jobs = self.list_jobs(status="pending")
        done_jobs = self.list_jobs(status="done")
        error_jobs = self.list_jobs(status="error")

        return {
            "coverage_gaps": len(gaps),
            "top_gaps": [{"topic": g.topic, "deficit": g.deficit, "difficulty": g.difficulty} for g in gaps[:5]],
            "jobs": {
                "pending": len(pending_jobs),
                "done": len(done_jobs),
                "error": len(error_jobs),
            },
            "scope_requests": scope_stats,
            "question_stats": {
                "total": question_stats["total"],
                "validated": question_stats["validated"],
            },
        }
