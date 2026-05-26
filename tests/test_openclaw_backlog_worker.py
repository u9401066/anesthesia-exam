from __future__ import annotations

import json
from pathlib import Path

from src.application.services.openclaw_backlog_worker import OpenClawBacklogWorker


class FakeHeartbeat:
    def __init__(self, jobs: list[dict], jobs_dir: Path):
        self._jobs = jobs
        self.jobs_dir = jobs_dir
        self.run_calls = []
        self.done_calls = []
        self.error_calls = []

    def run_heartbeat(self, max_requests: int, dry_run: bool = False):
        self.run_calls.append({"max_requests": max_requests, "dry_run": dry_run})
        return type(
            "HeartbeatResultStub",
            (),
            {
                "to_dict": lambda _self: {
                    "gaps_found": 1,
                    "jobs_written": 0,
                    "job_paths": [],
                    "skipped": 1,
                    "errors": [],
                }
            },
        )()

    def list_jobs(self, status=None):
        if status is None:
            return list(self._jobs)
        return [job for job in self._jobs if job.get("status") == status]

    def mark_job_done(self, job_path, questions_generated=0):
        self.done_calls.append((str(job_path), questions_generated))

    def mark_job_error(self, job_path, error_msg):
        self.error_calls.append((str(job_path), error_msg))


class FakeProvider:
    name = "openclaw"

    def __init__(self, response: str = '{"saved_count": 2, "question_ids": ["q1", "q2"]}'):
        self.response = response
        self.prompts = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeDispatchService:
    def __init__(self):
        self.calls = []

    def dispatch(self, request_id, provider):
        self.calls.append((request_id, provider.name))
        return type("DispatchResultStub", (), {"generated_count": 3, "summary": "ok"})()


def write_job(path: Path, payload: dict) -> dict:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    payload = dict(payload)
    payload["_path"] = str(path)
    return payload


def test_worker_dispatches_scope_request_job_and_marks_done(tmp_path: Path):
    job_path = tmp_path / "heartbeat_scope.json"
    job = write_job(
        job_path,
        {
            "job_id": "heartbeat_scope",
            "status": "pending",
            "topic": "airway",
            "source_request_id": "scope_123",
            "prompt": "make questions",
        },
    )
    heartbeat = FakeHeartbeat([job], tmp_path)
    dispatch = FakeDispatchService()
    provider = FakeProvider()

    result = OpenClawBacklogWorker(heartbeat=heartbeat, dispatch_service=dispatch).run_once(
        provider=provider,
        max_jobs=1,
        generate_jobs=False,
    )

    assert result.processed_jobs == 1
    assert result.generated_questions == 3
    assert dispatch.calls == [("scope_123", "openclaw")]
    assert heartbeat.done_calls == [(str(job_path), 3)]
    assert heartbeat.error_calls == []


def test_worker_runs_prompt_job_without_scope_request(tmp_path: Path):
    job_path = tmp_path / "heartbeat_prompt.json"
    job = write_job(
        job_path,
        {
            "job_id": "heartbeat_prompt",
            "status": "pending",
            "topic": "propofol",
            "prompt": "make propofol questions",
        },
    )
    heartbeat = FakeHeartbeat([job], tmp_path)
    provider = FakeProvider('{"saved_count": 2, "question_ids": ["q1", "q2"], "summary": "saved"}')

    result = OpenClawBacklogWorker(heartbeat=heartbeat).run_once(
        provider=provider,
        max_jobs=1,
        generate_jobs=False,
        process_auto_jobs=True,
    )

    assert result.processed_jobs == 1
    assert result.generated_questions == 2
    assert len(provider.prompts) == 1
    assert "最後只輸出 JSON" in provider.prompts[0]
    assert "本輪只處理 1 題" in provider.prompts[0]
    assert "不要先輸出計畫" in provider.prompts[0]
    assert heartbeat.done_calls == [(str(job_path), 2)]


def test_worker_dry_run_does_not_dispatch_or_mark_jobs(tmp_path: Path):
    job_path = tmp_path / "heartbeat_dry.json"
    job = write_job(
        job_path,
        {
            "job_id": "heartbeat_dry",
            "status": "pending",
            "topic": "ketamine",
            "prompt": "make ketamine questions",
        },
    )
    heartbeat = FakeHeartbeat([job], tmp_path)
    provider = FakeProvider()

    result = OpenClawBacklogWorker(heartbeat=heartbeat).run_once(
        provider=provider,
        max_jobs=1,
        generate_jobs=True,
        dry_run=True,
    )

    assert result.processed_jobs == 0
    assert result.generated_questions == 0
    assert heartbeat.run_calls == [{"max_requests": 5, "dry_run": True}]
    assert provider.prompts == []
    assert heartbeat.done_calls == []
    assert heartbeat.error_calls == []


def test_worker_marks_prompt_job_error_when_openclaw_saves_no_questions(tmp_path: Path):
    job_path = tmp_path / "heartbeat_blocked.json"
    job = write_job(
        job_path,
        {
            "job_id": "heartbeat_blocked",
            "status": "pending",
            "topic": "malignant hyperthermia",
            "prompt": "make malignant hyperthermia questions",
        },
    )
    heartbeat = FakeHeartbeat([job], tmp_path)
    provider = FakeProvider('{"saved_count": 0, "summary": "blocked: no precise source"}')

    result = OpenClawBacklogWorker(heartbeat=heartbeat).run_once(
        provider=provider,
        max_jobs=1,
        generate_jobs=False,
        process_auto_jobs=True,
    )

    assert result.processed_jobs == 0
    assert result.generated_questions == 0
    assert len(result.errors) == 1
    assert "saved_count > 0" in result.errors[0]
    assert heartbeat.done_calls == []
    assert heartbeat.error_calls == [(str(job_path), result.errors[0])]


def test_worker_skips_auto_coverage_jobs_by_default(tmp_path: Path):
    job_path = tmp_path / "heartbeat_auto.json"
    job = write_job(
        job_path,
        {
            "job_id": "heartbeat_auto",
            "status": "pending",
            "topic": "airway",
            "prompt": "make airway questions",
        },
    )
    heartbeat = FakeHeartbeat([job], tmp_path)
    provider = FakeProvider()

    result = OpenClawBacklogWorker(heartbeat=heartbeat).run_once(
        provider=provider,
        max_jobs=1,
        generate_jobs=False,
    )

    assert result.processed_jobs == 0
    assert result.skipped_jobs == 1
    assert provider.prompts == []
    assert heartbeat.done_calls == []
    assert heartbeat.error_calls == []
