"""LIVE_AGENT_EVAL=true python -m pytest tests/evals -v -rs.

Every provider call runs with a fresh fixed SQLite database under SQL write guards.
No application global database, schedule generation API or persistent turn is used.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event

from backend.app.config import positive_seconds
from backend.app.execution import ExecutionTimeout
from backend.app.services.agent_router import AgentRouter
from backend.app.services.llm_client import AgentLLMClient, AIUnavailableError
from backend.app.services.read_query import PROMPT_VERSION, READ_TOOL_ALLOWLIST, ReadQueryPlan
from backend.app.services.read_response import fact_sentences, READ_ONLY_NOTICE
from backend.app.services.read_turn import preview_read_turn
from tests.read_fixtures import WEEK, PREVIOUS_MESSAGES, database_snapshot, seed_read_fixture

CASE_FILE = Path(os.getenv("LLM_EVAL_CASE_FILE") or Path(__file__).with_name("agent_cases.json"))
CASES = json.loads(CASE_FILE.read_text(encoding="utf-8"))


class RecordingLLM(AgentLLMClient):
    def __init__(self):
        super().__init__()
        self.outputs = []
        self.enabled = True
        self.model = os.getenv("LLM_EVAL_MODEL") or self.model
        # Provider calls get their own bounded transport budget. The complete
        # AgentService turn has a separate, longer budget configured below.
        timeout = positive_seconds("LLM_EVAL_TIMEOUT_SECONDS", 120)
        self.timeout = httpx.Timeout(
            connect=self.timeout.connect,
            read=timeout,
            write=self.timeout.write,
            pool=self.timeout.pool,
        )

    def _post(self, payload, *, stage=None, read_timeout_seconds=None):
        response, latency, status = super()._post(
            payload, stage=stage, read_timeout_seconds=read_timeout_seconds
        )
        # Retain visible raw content even when JSON/schema validation fails later.
        # Do not persist provider hidden reasoning, headers or request prompts.
        message = (response.get("choices") or [{}])[0].get("message", {})
        self.outputs.append({"stage": stage, "raw_content": message.get("content"),
                             "latency_ms": latency, "provider_status": status})
        return response, latency, status

    def complete_json(self, **kwargs):
        started = time.monotonic()
        try:
            result = super().complete_json(**kwargs)
            self.outputs.append({"stage": kwargs.get("stage"), "output": result,
                                 "duration_ms": round((time.monotonic() - started) * 1000)})
            return result
        except AIUnavailableError as exc:
            self.outputs.append({"stage": kwargs.get("stage"), "error": exc.public_details})
            raise


def check_raw_plan(case, outputs):
    """Report provider mistakes separately from successful server corrections."""
    command = next((c["output"] for c in outputs if c.get("stage") == "agent_semantic" and "output" in c), None)
    if command is None:
        return [{"category": "provider_error", "detail": "No valid raw TurnCommand"}]
    findings = []
    if command.get("mutation_requested") or command.get("edits") or command.get("staffing_constraints") or command.get("execution") not in {"none", "analyze", "advice"}:
        findings.append({"category": "wrong_intent", "detail": command.get("execution")})
    plan = command.get("read_query") or {}
    if plan.get("question_type") != case["expected"]["question_type"]:
        findings.append({"category": "wrong_question_hint", "detail": plan.get("question_type")})
    return findings


def check_case(case, result):
    failures = []
    def fail(category, detail):
        failures.append({"category": category, "detail": detail})
    expected = case["expected"]
    if result.get("rejected"):
        fail("wrong_intent", result["rejected"])
        return failures
    plan = ReadQueryPlan.model_validate(result["query_plan"])
    for field, category in (("question_type", "wrong_intent"), ("target_week", "wrong_week"),
                            ("day", "wrong_day"), ("shift", "wrong_shift"), ("employee_ids", "wrong_employee"),
                            ("reference_mode", "implicit_history_reference")):
        actual = result["query_plan"][field]
        if actual != expected[field]:
            fail(category, {"field": field, "expected": expected[field], "actual": actual})
    calls = result["tool_calls"]
    names = [c["tool_name"] for c in calls]
    for name in names:
        if name not in case["allowed_tools"] or name in case["forbidden_tools"]:
            fail("forbidden_mutation" if name not in READ_TOOL_ALLOWLIST else "wrong_tool", name)
    if names != expected["tools"]:
        fail("wrong_tool", names)
    for call in calls:
        if call["input"]["target_week"] != expected["target_week"]:
            fail("wrong_week", "tool parameters")
        if "plan" in call["input"] and call["input"]["plan"] != result["query_plan"]:
            fail("fact_mismatch", "tool plan parameters")
    facts = result["facts"]
    if plan.reference_mode == "none":
        slots = facts.get("slots", [])
        if expected.get("shifts") and [s["shift"] for s in slots] != expected["shifts"]:
            fail("wrong_shift", "tool output shifts")
        # Independent expected values, not a self-consistency assertion alone.
        for slot in slots:
            if slot["day"] == "Sun":
                expected_ids = [f"E{i:02d}" for i in ([1, 2, 3, 4, 5, 6, 15] if slot["shift"] == "morning" else [7, 8, 9, 10, 11, 12])]
                if sorted(a["employee_id"] for a in slot["assignments"]) != expected_ids:
                    fail("wrong_employee", "fixed Sunday fixture differs")
                if slot["actual_staff"] != len(expected_ids) or slot["minimum_staff"] != 6 or slot["excess_staff"] != len(expected_ids) - 6:
                    fail("fact_mismatch", "fixed Sunday staffing differs")
            rows = {r["rule_id"]: r for r in slot["validation"]["coverage"]}
            if rows["R04"]["actual"] != slot["actual_staff"]:
                fail("fact_mismatch", "validator staffing differs")
        expected_sentences = fact_sentences(plan, facts)
        actual_sentences = result["final_answer"].split("\n\n")
        if sorted(actual_sentences) != sorted([*expected_sentences, READ_ONLY_NOTICE]):
            fail("hallucinated_fact", "answer contains missing, modified or ungrounded facts")
        if result["composition"].get("composition_mode") != "llm_grounded":
            fail("incomplete_answer", result["composition"])
    for phrase in case["answer_rubric"]["must_contain"]:
        if phrase not in result["final_answer"]:
            fail("incomplete_answer", phrase)
    if READ_ONLY_NOTICE not in result["final_answer"]:
        fail("incomplete_answer", "read-only notice missing")
    events = result["execution_events"]
    if not events or events[-1]["stage"] != "turn_completed" or not any(e["stage"] == "agent_route" for e in events):
        fail("incomplete_answer", "execution timeline missing")
    return failures


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_live_read_agent(case, database, monkeypatch, evaluation_output_dir):
    output = evaluation_output_dir / f"case-{case['name']}.json"
    if os.getenv("LIVE_AGENT_EVAL", "false").lower() != "true" or not os.getenv("LLM_API_KEY", "").strip():
        reason = "LIVE_AGENT_EVAL is disabled" if os.getenv("LIVE_AGENT_EVAL", "false").lower() != "true" else "LLM_API_KEY is missing"
        output.write_text(json.dumps({"name": case["name"], "status": "skipped", "reason": reason}), encoding="utf-8")
        pytest.skip(reason)
    turn_timeout = positive_seconds("LLM_EVAL_TURN_TIMEOUT_SECONDS", 300)
    monkeypatch.setenv("AGENT_TURN_TIMEOUT_SECONDS", str(turn_timeout))
    service = seed_read_fixture(database)
    llm = RecordingLLM()
    service.llm = llm
    service.router = AgentRouter(llm)
    before = database_snapshot(database)
    blocked_writes = []
    def guard(conn, cursor, statement, parameters, context, executemany):
        operation = statement.lstrip().split(None, 1)[0].upper()
        if operation not in {"SELECT", "PRAGMA", "BEGIN", "COMMIT", "ROLLBACK"}:
            blocked_writes.append(operation)
            raise AssertionError("forbidden_mutation")
    # SQLite read-only mode also blocks mutation via statements hidden in a CTE.
    def read_only_connection(dbapi_connection, record, proxy):
        dbapi_connection.execute("PRAGMA query_only=ON")
    event.listen(database.engine, "checkout", read_only_connection)
    event.listen(database.engine, "before_cursor_execute", guard)
    started = time.monotonic()
    result, failures = {}, []
    try:
        result = preview_read_turn(service, content=case["messages"][-1], current_week_start=WEEK,
                                   recent_messages=case["previous_conversation_state"])
        failures.extend(check_case(case, result))
    except (AIUnavailableError, ExecutionTimeout) as exc:
        failures.append({"category": "timeout" if "timeout" in getattr(exc, "error_type", "") else "provider_error", "detail": type(exc).__name__})
    except Exception as exc:
        failures.append({"category": "forbidden_mutation" if blocked_writes else "provider_error", "detail": type(exc).__name__})
    finally:
        if database_snapshot(database) != before or blocked_writes:
            failures.append({"category": "forbidden_mutation", "detail": "database writes attempted or snapshot changed"})
        event.remove(database.engine, "checkout", read_only_connection)
        event.remove(database.engine, "before_cursor_execute", guard)
        llm.close()
    run = service.router.last_run
    if not run or run.error_type or not run.results.get("agent_semantic"):
        failures.append({"category": "provider_error", "detail": run.error_type if run else "missing router call"})
    if run and run.latency_ms >= 120000:
        failures.append({"category": "timeout", "detail": "router watchdog exceeded"})
    record = {"name": case["name"], "status": "failed" if failures else "passed", "model": llm.model,
              "started_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": time.monotonic() - started,
              "prompt_version": PROMPT_VERSION, "dry_run": True, "database_unchanged": database_snapshot(database) == before,
              "raw_model_outputs": llm.outputs, "raw_plan_failures": check_raw_plan(case, llm.outputs),
              "router_latency_ms": sum(s["latency_ms"] for s in run.stages) if run else None,
              "fallback_used": run.fallback_used if run else False,
              "schema_bytes": max((s["schema_bytes"] for s in run.stages), default=0) if run else 0,
              "router_stages": run.stages if run else [],
              **result, "failures": failures}
    # Never serialize clients, request headers, provider credentials or environment values.
    serialized = json.dumps(record, ensure_ascii=False, indent=2, default=str)
    if llm.api_key:
        serialized = serialized.replace(llm.api_key, "[REDACTED]")
    output.write_text(serialized, encoding="utf-8")
    assert not failures, json.dumps(failures, ensure_ascii=False)
