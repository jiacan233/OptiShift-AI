"""Opt-in, real HTTP/SSE acceptance; never mocks or injects conversation state.

Run from the repository with the same interpreter used for the backend::

    python scripts/agent_multiturn_live.py --prepare-only
    python scripts/agent_multiturn_live.py --cases A-N

Each attempt gets a new evidence directory. Each case starts its own backend and
database copied from an independently validated fixture. Only fixture preparation
writes business data directly, before any conversation exists. Evidence snapshots
use SQLite read-only transactions. Existing evidence is never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections import Counter
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASE_FILE = ROOT / "tests/evals/multiturn_cases.json"
VARIANT_CASE_FILE = ROOT / "tests/evals/multiturn_variants.json"
SECRETS: list[str] = []


def redact(value: str) -> str:
    for secret in SECRETS:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        redact(json.dumps(value, ensure_ascii=False, indent=2, default=str)) + "\n",
        encoding="utf-8",
    )


def append_json(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(redact(json.dumps(value, ensure_ascii=False, default=str)) + "\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    """Match the dialogue agent's canonical JSON digest for evidence checks."""
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode())


def source_fingerprint() -> dict:
    """Hash untracked implementation too; never include .env or generated evidence."""

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)

    files = git(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "backend",
        "frontend/src",
        "scripts",
        "tests",
        "requirements.txt",
        "pyproject.toml",
    )
    hashes = {}
    for item in files.decode().splitlines():
        path = ROOT / item
        if path.is_file() and path.suffix not in {".db", ".zip", ".log"}:
            hashes[item] = sha256(path.read_bytes())
    return {
        "git_sha": git("rev-parse", "HEAD").decode().strip(),
        "tracked_diff_sha256": sha256(git("diff", "HEAD", "--binary")),
        "source_tree_sha256": sha256(json.dumps(hashes, sort_keys=True).encode()),
        "source_files_sha256": hashes,
        "dirty_paths": git("status", "--porcelain", "--untracked-files=normal")
        .decode()
        .splitlines(),
    }


def snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        result = {}
        tables = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for (table,) in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = []
            for row in connection.execute(f"SELECT * FROM {quoted}"):
                decoded = dict(row)
                for key, value in decoded.items():
                    if isinstance(value, str) and value[:1] in {"[", "{"}:
                        try:
                            decoded[key] = json.loads(value)
                        except ValueError:
                            pass
                rows.append(decoded)
            result[table] = rows
        return result
    finally:
        connection.rollback()
        connection.close()


def prepare_fixture(path: Path, week: date, *, fairness: bool = False) -> dict:
    """Canonical E01-E20, real rules, previous week + target confirmed schedules."""
    os.environ["APP_ENV"] = "test"
    from backend.app.database import Database, seed_demo_employees
    from backend.app.repository import EmployeeRepository, ScheduleRepository
    from backend.app.services.scheduling_service import SchedulingService

    if path.exists():
        raise FileExistsError(f"Refusing to reuse fixture {path}")
    database = Database(path)
    database.initialize()
    seed_demo_employees(database)
    service = SchedulingService(EmployeeRepository(database), ScheduleRepository(database))
    records = []
    for target in (week - timedelta(days=7), week):
        result = service.generate(week_start=target)
        if result.get("status") != "feasible" or not result.get("validation", {}).get(
            "confirmable"
        ):
            raise RuntimeError(
                f"Fixture generation failed: {target}: {json.dumps(result, ensure_ascii=False)}"
            )
        proof = None
        if fairness and target == week:
            proof = worsen_fairness_fixture(database, service, result["schedule_id"])
        confirmed = service.confirm(result["schedule_id"], result["version"])
        records.append(
            {"week_start": target.isoformat(), "result": confirmed, "fairness_opportunity": proof}
        )
    database.dispose()
    final = snapshot(path)
    if final.get("conversations") or any(row["status"] == "draft" for row in final["schedules"]):
        raise AssertionError("Fixture must start with no conversation or pending draft")
    return {
        "fixture": "canonical-demo-roster-v3",
        "target_week": week,
        "records": records,
        "database_sha256": sha256(path.read_bytes()),
        "snapshot": final,
    }


def worsen_fairness_fixture(database, service, schedule_id: str) -> dict:
    """Create a legal, deliberately uneven baseline and prove a legal improvement.

    This changes fixture assignments BEFORE the live case. The reverse transfer is
    a witness, never injected into suggestions or scenario state during testing.
    """
    from sqlalchemy import delete

    from backend.app.models import Assignment
    from backend.app.models.orm import AssignmentRecord, ScheduleRecord
    from backend.app.services.explanation import normalize_validation
    from backend.app.validator.authorization import classify_validation

    original = service.schedules.get(schedule_id)
    employees = service.employees.list()
    counts = Counter(a.employee_id for a in original.assignments)
    context = service.context_builder.build(original.week_start, allow_history_bootstrap=False)
    best = None
    before_gap = max(counts.get(e.id, 0) for e in employees) - min(
        counts.get(e.id, 0) for e in employees
    )
    before_square = sum(counts.get(e.id, 0) ** 2 for e in employees)
    for assignment in original.assignments:
        for employee in employees:
            if (
                employee.id == assignment.employee_id
                or counts[employee.id] < counts[assignment.employee_id]
            ):
                continue
            replacement = Assignment(
                employee_id=employee.id, day=assignment.day, shift=assignment.shift
            )
            changed = [replacement if item == assignment else item for item in original.assignments]
            candidate = original.model_copy(update={"assignments": changed})
            validation = classify_validation(
                normalize_validation(
                    service.validator.validate(
                        candidate, employees, context=context, rules=context.rules
                    )
                ),
                original.week_start,
                [],
            )
            if not validation["confirmable"]:
                continue
            after = Counter(a.employee_id for a in changed)
            square = sum(after.get(e.id, 0) ** 2 for e in employees)
            gap = max(after.get(e.id, 0) for e in employees) - min(
                after.get(e.id, 0) for e in employees
            )
            if square > before_square and (best is None or (gap, square) > best[0]):
                best = ((gap, square), candidate, validation, assignment, replacement)
    if best is None:
        raise AssertionError(
            "Could not prepare an independently legal fairness improvement opportunity"
        )
    (gap, square), candidate, validation, original_assignment, replacement = best
    with database.transaction(immediate=True) as session:
        session.execute(delete(AssignmentRecord).where(AssignmentRecord.schedule_id == schedule_id))
        session.add_all(
            [
                AssignmentRecord(schedule_id=schedule_id, **a.model_dump(mode="json"))
                for a in candidate.assignments
            ]
        )
        record = session.get(ScheduleRecord, schedule_id)
        record.validation_json = validation
        metadata = dict(record.metadata_json)
        metadata["fixture_preparation"] = "independently validated legal imbalance"
        metadata["metrics"] = {
            **metadata.get("metrics", {}),
            "workload_gap": gap,
            "fixture_workload_square": square,
        }
        record.metadata_json = metadata
    return {
        "baseline_workload_gap": gap,
        "improved_workload_gap": before_gap,
        "baseline_sum_squared_shifts": square,
        "improved_sum_squared_shifts": before_square,
        "legal_improvement": [
            {**replacement.model_dump(mode="json"), "type": "unassign"},
            {**original_assignment.model_dump(mode="json"), "type": "assign"},
        ],
        "validation": (
            "Both baseline and reverse transfer independently validated "
            "with actual rules and previous-week history"
        ),
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(args) -> None:
    """Thin test-only observer around the real app; no debug HTTP endpoint."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    SECRETS.extend(
        value
        for name, value in os.environ.items()
        if any(token in name.upper() for token in ("KEY", "SECRET", "PASSWORD", "TOKEN"))
        and len(value) > 5
    )
    import uvicorn

    from backend.app.execution import current_execution
    from backend.app.services.llm_client import AgentLLMClient

    original_post = AgentLLMClient._post
    lock = threading.Lock()
    provider_log = args.case_dir / "provider.jsonl"

    def observed_post(self, payload, **kwargs):
        trace = current_execution.get()
        event = {
            "event": "provider_request",
            "request_id": uuid4().hex,
            "started_at": datetime.now(UTC).isoformat(),
            "conversation_id": trace.conversation_id if trace else None,
            "client_message_id": trace.client_message_id if trace else None,
            "stage": kwargs.get("stage"),
            "model": self.model,
            "service_id": sha256((urlsplit(self.base_url).hostname or "").encode())[:16],
        }
        started = time.perf_counter()
        try:
            result = original_post(self, payload, **kwargs)
            event.update(status="completed", provider_status=result[2])
            return result
        except Exception as exc:
            event.update(
                status="failed",
                error_type=getattr(exc, "error_type", type(exc).__name__),
                provider_status=getattr(exc, "provider_status", None),
            )
            raise
        finally:
            event["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            with lock:
                append_json(provider_log, event)

    AgentLLMClient._post = observed_post
    # This instrumentation delegates every real request exactly once, retaining
    # actual success/failure and no prompts, authorization headers or reasoning.
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port, log_level="info")


class Backend:
    def __init__(self, path: Path, database: Path):
        self.path, self.database = path, database
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.process = None
        self.log = None

    def start(self) -> None:
        import httpx

        environment = {
            **os.environ,
            "APP_ENV": "test",
            "DATABASE_URL": str(self.database),
            "LLM_ENABLED": "true",
            "PYTHONIOENCODING": "utf-8",
            "LOG_LEVEL": "INFO",
        }
        self.log = (self.path / "backend.log").open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                "--case-dir",
                str(self.path),
                "--port",
                str(self.port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Backend exited before health check; inspect backend.log")
            try:
                if httpx.get(self.url + "/health", timeout=2).is_success:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.15)
        raise TimeoutError("Backend did not start within 40 seconds")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
        log_path = self.path / "backend.log"
        if log_path.exists():
            log_path.write_text(
                redact(log_path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8"
            )


def send_turn(
    client,
    backend: Backend,
    conversation: str,
    workspace: str,
    turn: dict,
    week: str,
    timeout: float,
) -> dict:
    turn_id = str(turn.get("turn", "extra"))
    client_message_id = "live_" + uuid4().hex
    body = {
        "browser_workspace_id": workspace,
        "client_message_id": client_message_id,
        "content": turn["content"],
        "current_week_start": week,
    }
    record = {
        "original_turn": turn_id,
        "inserted": bool(turn.get("inserted")),
        "request": body,
        "conversation_id": conversation,
        "target_url": backend.url,
        "state_before": snapshot(backend.database),
        "events": [],
    }
    started = time.perf_counter()
    raw_path = backend.path / f"turn-{turn_id}-{client_message_id}.sse"
    event_name, data_lines, terminal = "message", [], None
    try:
        with (
            raw_path.open("w", encoding="utf-8", newline="") as raw,
            client.stream(
                "POST",
                f"/api/agent/conversations/{conversation}/messages/stream",
                json=body,
                timeout=timeout,
                headers={"X-Request-ID": client_message_id},
            ) as response,
        ):
            record["http_status"] = response.status_code
            record["request_id"] = response.headers.get("x-request-id")
            for line in response.iter_lines():
                raw.write(redact(line) + "\n")
                raw.flush()
                if not line:
                    if data_lines:
                        text = "\n".join(data_lines)
                        try:
                            payload = json.loads(text)
                        except ValueError:
                            payload = {"unparsed": text}
                        event = {
                            "event": event_name,
                            "data": payload,
                            "http_elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                        }
                        record["events"].append(event)
                        if event_name in {"result", "error"}:
                            terminal = event
                    event_name, data_lines = "message", []
                elif line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
    except Exception as exc:
        record["transport_error"] = {"type": type(exc).__name__, "message": redact(str(exc))}
    record["http_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    record["terminal"] = terminal
    # Poll actual lease + persisted assistant, never advance based on HTTP 200
    # or a stale assistant elsewhere in the conversation.
    deadline = time.monotonic() + min(timeout, 310)
    while True:
        after = snapshot(backend.database)
        users = [
            m
            for m in after.get("conversation_messages", [])
            if m.get("conversation_id") == conversation
            and m.get("client_message_id") == client_message_id
            and m.get("role") == "user"
        ]
        assistants = [
            m
            for m in after.get("conversation_messages", [])
            if m.get("conversation_id") == conversation
            and m.get("role") == "assistant"
            and users
            and m.get("sequence_number", 0) > users[0]["sequence_number"]
        ]
        busy = any(
            c.get("active_turn_message_id")
            for c in after.get("conversations", [])
            if c["conversation_id"] == conversation
        )
        if not busy and (assistants or (terminal and terminal["event"] == "error") or not users):
            break
        if time.monotonic() > deadline:
            record["settlement_error"] = (
                "Turn did not release its lease and persist an assistant response"
            )
            break
        time.sleep(0.15)
    record["state_after"] = after
    record["persisted_user_messages"] = users
    record["persisted_assistant_messages"] = assistants
    record["settled"] = not busy
    record["elapsed_including_settlement_ms"] = round((time.perf_counter() - started) * 1000, 2)
    record["tool_calls"] = [
        t
        for t in after.get("agent_tool_calls", [])
        if users and t.get("message_id") == users[0]["message_id"]
    ]
    record["new_schedules"] = [
        s
        for s in after.get("schedules", [])
        if s["schedule_id"]
        not in {old["schedule_id"] for old in record["state_before"].get("schedules", [])}
    ]
    providers = backend.path / "provider.jsonl"
    record["provider_calls"] = (
        [
            json.loads(line)
            for line in providers.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("client_message_id") == client_message_id
        ]
        if providers.exists()
        else []
    )
    record["sse_file"] = raw_path.name
    write_json(backend.path / f"turn-{turn_id}.json", record)
    return record


def normalize_conditions(values: list) -> list[tuple]:
    """Read both atomic conditions and the legacy multi-day Scenario projection."""
    return sorted(
        (
            str(v.get("employee_id")),
            str(day),
            str(v.get("type") or v.get("change_type")).lower(),
            str(v.get("shift") or ""),
        )
        for v in values
        if isinstance(v, dict)
        for day in ([v["day"]] if v.get("day") else v.get("days", []))
    )


def dialogue_state(database_snapshot: dict, conversation: str, week: str) -> dict:
    for row in database_snapshot.get("conversation_dialogue_states", []):
        if row.get("conversation_id") == conversation and row.get("week_start") == week:
            return row.get("payload", {})
    return {}


def condition_changes(state: dict, kind: str = "conditions") -> list:
    return [change for condition in state.get(kind, []) for change in condition.get("changes", [])]


def case_checks(case: dict, turns: list[dict], final: dict, conversation: str) -> list[dict]:
    checks = []

    def check(name, passed, detail=None):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    messages = [turn for turn in turns if "request" in turn]
    check(
        "all_original_messages_sent",
        [t["request"]["content"] for t in messages if not t["inserted"]]
        == [t["content"] for t in case["turns"] if t["kind"] == "message"],
    )
    for turn in messages:
        number = turn["original_turn"]
        check(
            f"T{number}:terminal_sse_received",
            bool(turn.get("terminal")),
            turn.get("transport_error"),
        )
        check(f"T{number}:lease_released", turn.get("settled"), turn.get("settlement_error"))
        check(f"T{number}:persisted_reply", len(turn.get("persisted_assistant_messages", [])) == 1)
        check(
            f"T{number}:business_result_received",
            (turn.get("terminal") or {}).get("event") == "result",
            turn.get("terminal") if (turn.get("terminal") or {}).get("event") == "error" else None,
        )
        if turn is not messages[-1]:
            check(f"T{number}:no_premature_draft", not turn.get("new_schedules"))
        expected = case.get("checkpoints", {}).get(number, {})
        state = dialogue_state(turn["state_after"], conversation, case["week_start"])
        for key, value in expected.items():
            actual = None
            if key == "active":
                actual = condition_changes(state)
                passed = normalize_conditions(actual) == normalize_conditions(value)
            elif key == "proposal_contains":
                actual = condition_changes(state, "proposals")
                passed = set(normalize_conditions(value)) <= set(normalize_conditions(actual))
            elif key == "pending_contains":
                actual = state.get("pending", [])
                passed = any(all(p.get(k) == v for k, v in value.items()) for p in actual)
            elif key == "pending_empty":
                actual = state.get("pending", [])
                passed = not actual
            elif key == "has_conflict":
                actual = state.get("conflicts", [])
                passed = bool(actual)
            elif key == "conflict_empty":
                actual = state.get("conflicts", [])
                passed = not actual
            else:
                raise AssertionError(f"Unknown acceptance checkpoint: {key}")
            check(f"T{number}:{key}", passed, {"expected": value, "actual": actual})
    scenarios = [
        s
        for s in final.get("conversation_scenarios", [])
        if s.get("conversation_id") == conversation and s.get("week_start") == case["week_start"]
    ]
    active = scenarios[0].get("temporary_constraints", []) if scenarios else []
    state = dialogue_state(final, conversation, case["week_start"])
    check("persisted_dialogue_state_exists", bool(state))
    if case["expected_conditions"]:
        check(
            "final_exact_active_conditions",
            normalize_conditions(active) == normalize_conditions(case["expected_conditions"]),
            {"expected": case["expected_conditions"], "actual": active},
        )
    drafts = messages[-1].get("new_schedules", []) if messages else []
    if case["requires_new_draft"]:
        check(
            "final_turn_creates_new_draft",
            len(drafts) == 1 and drafts[0]["status"] == "draft",
            [d["schedule_id"] for d in drafts],
        )
    for draft in drafts:
        metadata = draft.get("metadata_json", {})
        check(
            "draft_independent_validator_passed",
            draft.get("validation_json", {}).get("confirmable")
            or draft.get("validation_json", {}).get("passed"),
        )
        expected_snapshot = metadata.get("condition_snapshot")
        check(
            "draft_condition_snapshot_present",
            isinstance(expected_snapshot, list),
            expected_snapshot,
        )
        if isinstance(expected_snapshot, list):
            check(
                "draft_condition_hash_matches_snapshot",
                metadata.get("condition_hash") == digest(expected_snapshot),
                metadata.get("condition_hash"),
            )
        dependencies = metadata.get("dependencies")
        if dependencies is not None:
            check(
                "draft_dependency_hash_matches_dependencies",
                metadata.get("dependency_hash") == digest(dependencies),
                metadata.get("dependency_hash"),
            )
        if case["expected_conditions"]:
            snapshot_for_compare = expected_snapshot if isinstance(expected_snapshot, list) else []
            check(
                "draft_condition_snapshot_matches_changes",
                normalize_conditions(snapshot_for_compare)
                == normalize_conditions(metadata.get("requested_changes", [])),
                {"snapshot": expected_snapshot, "requested_changes": metadata.get("requested_changes")},
            )
            check(
                "draft_condition_snapshot_matches_state",
                normalize_conditions(expected_snapshot) == normalize_conditions(active),
                {"snapshot": expected_snapshot, "active": active},
            )
            check(
                "draft_solver_conditions_match_specification",
                normalize_conditions(metadata.get("requested_changes", []))
                == normalize_conditions(case["expected_conditions"]),
                metadata.get("requested_changes"),
            )
        check(
            "draft_source_conversation",
            metadata.get("agent_conversation_id") == conversation
            or metadata.get("source_conversation_id") == conversation,
            metadata,
        )
        check(
            "draft_source_client_message",
            metadata.get("agent_client_message_id") == messages[-1]["request"]["client_message_id"]
            or metadata.get("source_client_message_id")
            == messages[-1]["request"]["client_message_id"],
        )
        check(
            "draft_scenario_revision",
            metadata.get("scenario_revision") == state.get("scenario_revision"),
        )
        check("draft_condition_hash_present", bool(metadata.get("condition_hash")))
        check("draft_dependency_hash_present", bool(metadata.get("dependency_hash")))
    # An allowed infeasible outcome must actually include a solver diagnosis.
    if not drafts and case["allow_infeasible"]:
        check(
            "infeasible_has_tool_diagnosis",
            any(
                isinstance(t.get("output_json"), dict)
                and t["output_json"].get("status") == "infeasible"
                and (t["output_json"].get("diagnosis") or t["output_json"].get("conflicts"))
                for t in (messages[-1].get("tool_calls", []) if messages else [])
            ),
        )
    return checks


def run_case(case: dict, directory: Path, fixture: Path, args) -> dict:
    import httpx

    directory.mkdir()
    database = directory / "case.db"
    shutil.copy2(fixture, database)
    backend = Backend(directory, database)
    turns = []
    result = {
        "id": case["id"],
        "case_specification": case,
        "database": str(database),
        "url": backend.url,
        "build_at_start": source_fingerprint(),
        "ui_verified": False,
    }
    try:
        backend.start()
        with httpx.Client(base_url=backend.url, timeout=30) as client:
            workspace = "live_" + uuid4().hex
            response = client.post(
                "/api/agent/conversations", json={"browser_workspace_id": workspace}
            )
            response.raise_for_status()
            created = response.json()
            conversation = (
                created.get("conversation_id") or created["conversation"]["conversation_id"]
            )
            result.update(conversation_id=conversation, browser_workspace_id=workspace)
            write_json(directory / "case-start.json", result)
            for turn in case["turns"]:
                print(f"{case['id']} T{turn['turn']} {turn['kind']}", flush=True)
                if turn["kind"] == "browser_refresh":
                    # GET proves server recovery only; never claim it is a real
                    # browser refresh. Browser coverage is separately required.
                    restored = client.get(
                        f"/api/agent/conversations/{conversation}",
                        params={"browser_workspace_id": workspace},
                    )
                    action = {
                        "original_turn": turn["turn"],
                        "kind": "server_reopen",
                        "required_action": turn["content"],
                        "http_status": restored.status_code,
                        "response": restored.json(),
                        "ui_verified": False,
                    }
                    turns.append(action)
                    write_json(directory / f"action-{turn['turn']}.json", action)
                    continue
                record = send_turn(
                    client, backend, conversation, workspace, turn, case["week_start"], args.timeout
                )
                turns.append(record)
                write_json(directory / "transcript.json", turns)
                if not record["settled"]:
                    result["stopped_reason"] = (
                        "Previous turn is still busy; refusing to overlap messages"
                    )
                    break
            final = snapshot(database)
            result["checks"] = case_checks(case, turns, final, conversation)
            result["status"] = (
                "passed_http_contract"
                if all(c["passed"] for c in result["checks"])
                else "product_failure"
            )
            result["browser_actions_pending"] = [t for t in case["turns"] if t["kind"] != "message"]
            result["semantic_review_required"] = case["expectation"]
            write_json(directory / "final-state.json", final)
    except Exception as exc:
        result.update(
            status="harness_failure",
            error={"type": type(exc).__name__, "message": redact(str(exc))},
        )
    finally:
        backend.stop()
        result["build_at_finish"] = source_fingerprint()
        result["source_changed_during_case"] = (
            result["build_at_start"]["source_tree_sha256"]
            != result["build_at_finish"]["source_tree_sha256"]
        )
        result["turn_count"] = len([t for t in turns if "request" in t])
        result["provider_requests"] = sum(len(t.get("provider_calls", [])) for t in turns)
        result["provider_failed_requests"] = sum(
            c["status"] == "failed" for t in turns for c in t.get("provider_calls", [])
        )
        if result.get("status") == "product_failure" and result["provider_failed_requests"]:
            result["provider_failures_present"] = True
        write_json(directory / "transcript.json", turns)
        write_json(directory / "summary.json", result)
    return result


def distribution(values: list[float]) -> dict:
    values = sorted(values)
    return {
        "n": len(values),
        "p50": values[min(len(values) - 1, math.ceil(len(values) * 0.5) - 1)] if values else None,
        "p95": values[min(len(values) - 1, math.ceil(len(values) * 0.95) - 1)] if values else None,
    }


def summarize(directory: Path, results: list[dict]) -> dict:
    turns = []
    for path in sorted(directory.glob("CASE_*/transcript.json")):
        turns.extend(t for t in json.loads(path.read_text(encoding="utf-8")) if "request" in t)
    stages: dict[str, list] = {}
    for turn in turns:
        for event in turn["events"]:
            payload = event.get("data", {})
            if event["event"] == "execution" and payload.get("duration_ms") is not None:
                stages.setdefault(payload["stage"], []).append(payload["duration_ms"])
    calls = [call for t in turns for call in t.get("provider_calls", [])]
    business_turns = {
        (call.get("conversation_id"), call.get("client_message_id"))
        for call in calls
        if call.get("conversation_id")
    }
    summary = {
        "cases": [
            {
                "id": r["id"],
                "status": r["status"],
                "turn_count": r["turn_count"],
                "provider_requests": r["provider_requests"],
                "failed_checks": [c for c in r.get("checks", []) if not c["passed"]],
            }
            for r in results
        ],
        "measurement_scope": (
            "HTTP total starts before POST and ends after SSE closes. Settlement includes "
            "database lease/reply polling. Stage durations are nested and must not be summed; "
            "browser timing is not measured by this HTTP runner."
        ),
        "http_total_ms": distribution([t["http_elapsed_ms"] for t in turns]),
        "settled_total_ms": distribution([t["elapsed_including_settlement_ms"] for t in turns]),
        "stage_ms": {stage: distribution(values) for stage, values in stages.items()},
        "provider_requests": len(calls),
        "provider_ms": distribution([c["duration_ms"] for c in calls]),
        "provider_business_turn_count": len(business_turns),
        "real_multiturn_provider_evidence": any(
            count >= 2 for count in Counter(conv for conv, _ in business_turns).values()
        )
        and any(c["status"] == "completed" for c in calls),
        "timeout_count": sum("timeout" in c.get("error_type", "").lower() for c in calls),
        "provider_failures": [c for c in calls if c["status"] == "failed"],
        "browser_verified": False,
        "complete_acceptance": False,
        "completion_note": (
            "HTTP contract assertions are only part of acceptance. Review per-case semantics "
            "and complete browser/recovery checks before declaring full acceptance."
        ),
    }
    write_json(directory / "summary.json", summary)
    return summary


def parse_cases(value: str) -> set[str]:
    result = set()
    for token in value.upper().split(","):
        token = token.strip().removeprefix("CASE_")
        if "-" in token:
            first, last = token.split("-", 1)
            result.update(f"CASE_{chr(c)}" for c in range(ord(first), ord(last) + 1))
        else:
            result.add("CASE_" + token)
    if not result <= {f"CASE_{chr(c)}" for c in range(ord("A"), ord("N") + 1)}:
        raise ValueError("Cases must be A-N or comma-separated letters")
    return result


def load_cases(*, selected: set[str], include_variants: bool) -> tuple[dict, list[dict]]:
    """Load original cases and optional text-only variants without weakening checks."""
    specification = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    cases = [case for case in specification["cases"] if case["id"] in selected]
    if not include_variants:
        return specification, cases
    variant_spec = json.loads(VARIANT_CASE_FILE.read_text(encoding="utf-8"))
    allowed_bases = {"CASE_A", "CASE_B", "CASE_E", "CASE_G", "CASE_H", "CASE_J"}
    for variant in variant_spec.get("variants", []):
        base_id = variant["base_case"]
        if base_id not in allowed_bases:
            raise ValueError(f"Variant base case is outside the approved repeat set: {base_id}")
        if base_id not in selected:
            continue
        base = next((item for item in cases if item["id"] == base_id), None)
        if base is None:
            continue
        variant_case = deepcopy(base)
        variant_case["id"] = variant["id"]
        variant_case["title"] = f"{base['title']} (natural-language variant)"
        variant_case["variant_of"] = base_id
        replacements = {str(turn["turn"]): turn for turn in variant["turns"]}
        for turn in variant_case["turns"]:
            replacement = replacements.get(str(turn["turn"]))
            if replacement:
                turn["content"] = replacement["content"]
        cases.append(variant_case)
    return specification, cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="A-N")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts/agent-multiturn-live")
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        help="Reuse this previously generated fixture directory, copied into this new run",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=330,
        help="HTTP transport watchdog; does not extend backend/LLM budgets",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Each repetition is an independent case database/application",
    )
    parser.add_argument(
        "--natural-variants",
        action="store_true",
        help="Also run opt-in natural-language variants for selected A/B/E/G/H/J cases",
    )
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--case-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        serve(args)
        return 0
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    SECRETS.extend(
        value
        for name, value in os.environ.items()
        if any(token in name.upper() for token in ("KEY", "SECRET", "PASSWORD", "TOKEN"))
        and len(value) > 5
    )
    selected = parse_cases(args.cases)
    specification, cases = load_cases(selected=selected, include_variants=args.natural_variants)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    directory = args.output_root.resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    print(f"Evidence: {directory}", flush=True)
    environment = {
        "APP_ENV": "test",
        "LLM_ENABLED": True,
        "model": os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        "service_id": sha256(
            (
                urlsplit(os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")).hostname or ""
            ).encode()
        )[:16],
        "credential_present": bool(os.getenv("LLM_API_KEY")),
        "target_week": specification["target_week"],
        "database": "SQLite, independent per case",
        "provider_observation": "Real AgentLLMClient._post delegated unchanged; metadata only",
        "python": sys.version,
        "http_timeout_seconds": args.timeout,
        "budgets": {
            k: os.environ.get(k)
            for k in [
                "AGENT_TURN_TIMEOUT_SECONDS",
                "LLM_READ_TIMEOUT_SECONDS",
                "LLM_CONNECT_TIMEOUT_SECONDS",
                "LLM_SEMANTIC_BUDGET_SECONDS",
                "LLM_RESPONSE_BUDGET_SECONDS",
            ]
        },
    }
    write_json(
        directory / "manifest.json",
        {
            "run_id": run_id,
            "build": source_fingerprint(),
            "environment": environment,
            "case_file_sha256": sha256(CASE_FILE.read_bytes()),
            "selected_cases": sorted(selected),
            "executed_case_ids": [case["id"] for case in cases],
            "natural_variants": args.natural_variants,
            "variant_case_file_sha256": sha256(VARIANT_CASE_FILE.read_bytes())
            if args.natural_variants and VARIANT_CASE_FILE.exists()
            else None,
            "repeat": args.repeat,
        },
    )
    if not args.prepare_only and not environment["credential_present"]:
        write_json(
            directory / "summary.json",
            {"status": "blocked", "reason": "LLM_API_KEY missing", "complete_acceptance": False},
        )
        print("Blocked: LLM_API_KEY missing; no live success claimed.", flush=True)
        return 2
    baseline_dir = directory / "baseline"
    baseline_dir.mkdir()
    for name, fairness in (("ordinary", False), ("fairness", True)):
        if name == "fairness" and "CASE_H" not in selected:
            continue
        db_path = baseline_dir / f"{name}.db"
        if args.baseline_dir:
            shutil.copy2(args.baseline_dir / f"{name}.db", db_path)
            shutil.copy2(args.baseline_dir / f"{name}.json", baseline_dir / f"{name}.json")
        else:
            print(f"Preparing independently validated {name} baseline", flush=True)
            write_json(
                baseline_dir / f"{name}.json",
                prepare_fixture(
                    db_path, date.fromisoformat(specification["target_week"]), fairness=fairness
                ),
            )
    if args.prepare_only:
        write_json(
            directory / "summary.json",
            {"status": "fixture_ready", "real_provider_calls": 0, "complete_acceptance": False},
        )
        return 0
    results = []
    for repetition in range(1, args.repeat + 1):
        for case in cases:
            name = case["id"] + (f"_repeat{repetition}" if repetition > 1 else "")
            fixture = baseline_dir / ("fairness.db" if case["id"] == "CASE_H" else "ordinary.db")
            result = run_case(case, directory / name, fixture, args)
            results.append(result)
            summarize(directory, results)
            print(
                f"{name}: {result['status']} ({result['provider_requests']} provider requests)",
                flush=True,
            )
    summary = summarize(directory, results)
    return (
        0
        if all(r["status"] == "passed_http_contract" for r in results)
        and summary["real_multiturn_provider_evidence"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
