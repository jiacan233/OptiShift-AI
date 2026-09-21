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
    {"name": "set_preserves_preference", "input": "把 E01 改成只周一请假，E02 周三晚班优先保持不变，再试排。", "kind": "set_keep"},
    {"name": "only_leave_followup", "input": "那如果只让 E01 周一请假呢？", "kind": "only_leave"},
    {"name": "two_preference_shifts", "input": "E02 周二早班优先 + 周三晚班优先，帮我试排一下", "kind": "two_preferences"},
    {"name": "preference_missing_shift", "input": "E02 周三优先，帮我重新排一下", "kind": "missing_shift"},
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
        from backend.app.models.dialogue import DialogueState, Condition
        from backend.app.services.dialogue_parser import parse_command
        from backend.app.services.router_stages import RouterRun
        from datetime import date
        state = DialogueState()
        kind = case["kind"]
        if kind in {"set_keep", "only_leave", "ordered"}:
            state.conditions = [Condition(id=f"condition_{i}", source_message_id="fixture",
                changes=[change]) for i, change in enumerate([
                    {"employee_id": "E01", "type": "leave", "day": "Mon"},
                    {"employee_id": "E01", "type": "leave", "day": "Tue"},
                    {"employee_id": "E02", "type": "preference", "day": "Wed", "shift": "evening"},
                ])]
            state.context_ids = [c.id for c in state.conditions]
        run = RouterRun()
        command = parse_command(case["input"], state, employees, llm, current_week_start=date(2026, 10, 5),
                                recent_messages=PREVIOUS_MESSAGES, run=run)
        result = router.route(case["input"], employees=employees, recent_messages=PREVIOUS_MESSAGES,
                              command=command, run=run)
        assert time.monotonic() - started < 120, "120-second watchdog exceeded"
        assert run.results.get("agent_semantic"), "No actual semantic provider result"
        assert any(o.get("provider_status") == 200 for o in llm.outputs), "No real HTTP 200"
        assert run.error_type is None, run.error_type
        assert all(len(e.employee_ids) <= 1 and len(e.days) <= 1 for e in command.edits)
        atoms = {(e.employee_ids[0], e.days[0].value, e.type.value, e.shift.value if e.shift else None)
                 for e in command.edits if e.employee_ids and e.days and e.type and e.operation == "add"}
        if kind in {"unspecified", "missing_shift"}:
            assert command.clarification or any(not e.days or not e.type or not e.shift for e in command.edits)
            assert not command.force_generate
        elif kind == "leave":
            assert command.execution == "create_draft"
            assert atoms == {("E01", "Mon", "leave", None)}
        elif kind == "force_missing":
            assert command.clarification and not (command.force_generate and command.requested_overrides)
        elif kind == "force":
            assert command.force_generate and command.execution == "create_draft"
            assert [(s.rule_id, s.employee_id, s.day.value, s.shift.value) for s in command.requested_overrides] == [("R08", "E01", "Wed", "morning")]
            assert [(a.employee_id, a.day.value, a.shift.value) for a in command.forced_assignments] == [("E01", "Wed", "morning")]
        elif kind in {"set_keep", "only_leave", "ordered"}:
            assert not command.clarification
            assert command.edits or command.reference != "none"
            assert command.execution != "create_draft"
            assert all(set(e.reference_ids) <= set(state.context_ids) for e in command.edits)
        elif kind == "two_preferences":
            assert command.execution == "preview"
            assert atoms == {("E02", "Tue", "preference", "morning"), ("E02", "Wed", "preference", "evening")}
        elif kind == "multi":
            assert command.execution == "create_draft"
            assert atoms == {("E01", "Mon", "leave", None), ("E01", "Tue", "leave", None), ("E02", "Wed", "preference", "evening")}
        else:
            assert not command.mutation_requested and not command.force_generate and not command.edits
            if kind == "hello":
                assert command.domain == "smalltalk"
            if kind in {"staffing", "history"}:
                assert command.read_query.day == "Sun"
                assert command.read_query.question_type == ("staffing_explanation" if kind == "staffing" else "schedule_overview")
            if kind == "feasibility":
                assert command.read_query.question_type == "feasibility_explanation"
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
              "turn_plan": run.results.get("agent_semantic"), "parser_results": run.results,
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
