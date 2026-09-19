"""Actual provider routing under a read-only SQLite guard; never execute a turn."""
import json
import os
import time

import pytest
from sqlalchemy import event

from backend.app.services.agent_router import AgentRouter
from backend.app.database import seed_demo_employees
from backend.app.repository import EmployeeRepository
from tests.evals.test_live_agent_eval import RecordingLLM
from tests.read_fixtures import PREVIOUS_MESSAGES, database_snapshot

CASES = [
    {"name": "e17_unspecified", "input": "把 E17 随便排到哪一天都行", "kind": "unspecified"},
    {"name": "e01_leave_replan", "input": "E01 周一请假，重新排一下", "kind": "leave"},
    {"name": "sunday_staffing", "input": "周日为什么安排了7个人？", "kind": "staffing"},
    {"name": "force_missing_scope", "input": "就算违反规则也先给我排出来", "kind": "force_missing"},
    {"name": "hello", "input": "你好", "kind": "hello"},
    {"name": "e17_feasibility", "input": "E17这周能不能排进去？", "kind": "feasibility"},
    {"name": "negative_force", "input": "不要强制生成，看看有没有别的办法", "kind": "negative"},
    {"name": "previous_suggestion", "input": "周日谁上班？", "kind": "history"},
    {"name": "multi_employee_days", "input": "E01 周一周二请假，E02 周三晚班优先，帮我重新排一下", "kind": "multi"},
    {"name": "ordered_operations", "input": "先清掉 E01 的限制，再给 E02 周五请假", "kind": "ordered"},
]


def evaluate_router(case, database, output_dir):
    output = output_dir / f"case-router-{case['name']}.json"
    if os.getenv("LIVE_AGENT_EVAL", "false").lower() != "true" or not os.getenv("LLM_API_KEY", "").strip():
        output.write_text(json.dumps({"name": case["name"], "status": "skipped"}), encoding="utf-8")
        pytest.skip("LIVE_AGENT_EVAL disabled or LLM_API_KEY missing")
    seed_demo_employees(database)
    employees = EmployeeRepository(database).list()
    llm = RecordingLLM()
    router = AgentRouter(llm)
    before = database_snapshot(database)
    blocked = []
    def readonly(connection, record, proxy):
        connection.execute("PRAGMA query_only=ON")
    def guard(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() not in {"SELECT", "PRAGMA", "BEGIN", "COMMIT", "ROLLBACK"}:
            blocked.append(statement.split(None, 1)[0])
            raise AssertionError("Router attempted database mutation")
    event.listen(database.engine, "checkout", readonly)
    event.listen(database.engine, "before_cursor_execute", guard)
    started = time.monotonic()
    result = None
    failures = []
    try:
        result = router.route(case["input"], employees=employees,
                              recent_messages=PREVIOUS_MESSAGES)
        elapsed = time.monotonic() - started
        assert elapsed < 120, "120-second watchdog exceeded"
        run = router.last_run
        assert run.results.get("agent_route_lite"), "No actual Lite provider result"
        assert any(o.get("provider_status") == 200 for o in llm.outputs), "No real HTTP 200"
        assert run.error_type is None, run.error_type
        assert result.reference.type == "none"
        kind = case["kind"]
        if kind == "unspecified":
            assert run.results["agent_route_lite"]["mutation_requested"]
            assert result.employees == ["E17"] and not result.changes and not result.forced_assignments
            assert result.intent == "clarification" and not result.mutation_requested
            assert "agent_mutation" in run.results
        elif kind == "leave":
            assert result.intent == "replan" and result.mutation_requested
            assert [(c.employee_id, c.day.value, c.type.value) for c in result.changes] == [("E01", "Mon", "leave")]
        elif kind == "force_missing":
            assert run.results["agent_route_lite"]["force_or_override_intent"]
            assert "agent_force" in run.results
            assert result.intent == "clarification" and not result.force_generate and not result.requested_overrides
        elif kind == "force":
            assert result.force_generate and result.mutation_requested and "agent_force" in run.results
            assert [(s.rule_id, s.employee_id, s.day.value, s.shift.value) for s in result.requested_overrides] == [("R08", "E01", "Wed", "morning")]
            assert [(a.employee_id, a.day.value, a.shift.value) for a in result.forced_assignments] == [("E01", "Wed", "morning")]
        elif kind == "multi":
            assert result.mutation_requested
            assert [(c.employee_id, c.day.value, c.type.value, c.shift.value if c.shift else None) for c in result.changes] == [
                ("E01", "Mon", "leave", None), ("E01", "Tue", "leave", None), ("E02", "Wed", "preference", "evening")]
        elif kind == "ordered":
            assert result.mutation_requested
            assert [(o.operation, o.employee_id, o.day.value if o.day else None) for o in result.operations] == [("clear", "E01", None), ("add", "E02", "Fri")]
        else:
            assert not result.mutation_requested and not result.force_generate and not result.changes
            if kind == "hello":
                assert result.intent == "ask"
            if kind in {"staffing", "history"}:
                assert result.read_query.day == "Sun"
                assert result.read_query.question_type == ("staffing_explanation" if kind == "staffing" else "schedule_overview")
            if kind == "feasibility":
                assert result.read_query.question_type == "feasibility_explanation"
    except Exception as exc:
        failures.append({"category": getattr(exc, "error_type", type(exc).__name__), "detail": str(exc)})
    finally:
        after = database_snapshot(database)
        if before != after or blocked:
            failures.append({"category": "forbidden_mutation"})
        event.remove(database.engine, "checkout", readonly)
        event.remove(database.engine, "before_cursor_execute", guard)
        llm.close()
    run = router.last_run
    record = {"name": "router-" + case["name"], "input": case["input"], "model": llm.model,
              "status": "failed" if failures else "passed", "failures": failures,
              "duration_seconds": time.monotonic() - started,
              "router_latency_ms": sum(s["latency_ms"] for s in run.stages),
              "fallback_used": run.fallback_used, "error_type": run.error_type,
              "schema_bytes": max((s["schema_bytes"] for s in run.stages), default=0),
              "lite_result": run.results.get("agent_route_lite"), "parser_results": run.results,
              "stages": run.stages, "final_route": result.model_dump(mode="json") if result else None,
              "provider_outputs": llm.outputs, "database_unchanged": before == after}
    serialized = json.dumps(record, ensure_ascii=False, indent=2)
    if llm.api_key:
        serialized = serialized.replace(llm.api_key, "[REDACTED]")
    output.write_text(serialized, encoding="utf-8")
    print(f"LIVE {record['name']} model={llm.model} latency_ms={record['router_latency_ms']} fallback={run.fallback_used} {record['status']}")
    assert not failures, json.dumps(failures, ensure_ascii=False)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_live_router(case, database, evaluation_output_dir):
    evaluate_router(case, database, evaluation_output_dir)
