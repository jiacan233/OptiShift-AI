"""Non-persisting entry point for exercising the real read router and tools.

This deliberately omits turn leases/message persistence. The same normalization,
week/reference resolution, snapshot tools and grounded composer serve normal
AgentService turns; HTTP persistence/SSE/idempotency are integration-tested there.
"""
from datetime import date

from ..execution import ExecutionTrace, current_execution, execution_stage
from .agent_router import AgentIntent, calibrate_read_route
from .read_query import READ_TOOL_ALLOWLIST, normalize_plan, tool_for_plan
from .read_response import compose_read_answer


def preview_read_turn(service, *, content: str, current_week_start: date,
                      recent_messages: list[dict]) -> dict:
    trace = ExecutionTrace("read-only-preview", "dry-run")
    token = current_execution.set(trace)
    calls = []
    try:
        trace.emit("turn_started", "started")
        employees = service.employees.list()
        route = service.router.route(content, employees=employees, recent_messages=recent_messages)
        route = calibrate_read_route(route, content, employees)
        if route.mutation_requested or route.intent not in {
            AgentIntent.ASK, AgentIntent.EXPLAIN, AgentIntent.ADVICE, AgentIntent.VALIDATE,
        }:
            return {"rejected": "wrong_intent", "route": route.model_dump(mode="json"),
                    "tool_calls": [], "execution_events": trace.finish(failed=True)}
        suggestion = service._resolve_suggestion(route, recent_messages)
        plan = normalize_plan(content, employees, proposal=route.read_query)
        route.read_query = plan
        target = service._resolve_week(content=content, route=route, current_week_start=current_week_start,
                                       messages=recent_messages, suggestion=suggestion)
        plan = normalize_plan(content, employees, target_week=target.week_start, proposal=plan)
        if plan.clarification or (plan.reference_mode == "suggestion" and suggestion is None):
            return {"rejected": "clarification", "query_plan": plan.model_dump(mode="json"),
                    "tool_calls": [], "execution_events": trace.finish(failed=True)}

        def call(name, **inputs):
            if name not in READ_TOOL_ALLOWLIST:
                raise ValueError("Forbidden mutation in read-only turn")
            with execution_stage("tool"):
                output = service.tools.run(name, **inputs)
            calls.append({"tool_name": name, "input": {
                k: v.isoformat() if isinstance(v, date) else v for k, v in inputs.items()
            }, "output": output, "status": "completed"})
            return output

        current = call("get_current_schedule", target_week=target.week_start, version=plan.version)
        if suggestion:
            route.intent = AgentIntent.EXPLAIN
            answer = service._compose_read_response(route=route, content=content, target=target,
                                                    current=current, tool_output=None, suggestion=suggestion)
            facts, composition = {"suggestion": suggestion}, {"composition_mode": "explicit_reference"}
        else:
            facts = call(tool_for_plan(plan), target_week=target.week_start,
                         plan=plan.model_dump(mode="json"), snapshot=current.get("display"))
            answer, composition = compose_read_answer(service.llm, question=content, plan=plan, facts=facts)
        return {"query_plan": plan.model_dump(mode="json"), "route": route.model_dump(mode="json"),
                "tool_calls": calls, "facts": facts, "final_answer": answer,
                "composition": composition, "execution_events": trace.finish()}
    finally:
        current_execution.reset(token)
