"""Stateful scheduling orchestration with separate recording and execution contracts."""
import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from uuid import uuid4

from ..execution import current_execution, execution_stage
from ..models.dialogue import Condition, Focus, TurnCommand
from ..models.domain import Assignment, Schedule, ScheduleChange
from ..models.scenario_changes import format_conditions
from ..repository.dialogue import DialogueRepository, patches_for
from ..repository.scenarios import ScenarioRevisionConflict
from .agent_router import AgentRouter
from .dialogue_reducer import detect_conflicts, reduce_command, unique_changes


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def describe(state):
    lines = [f"已记录 {len(state.conditions) + len(state.staffing_constraints)} 项有效要求。" if state.conditions or state.staffing_constraints else "当前没有已记录的完整条件。"]
    for constraint in state.staffing_constraints:
        days = {"Mon": "周一", "Tue": "周二", "Wed": "周三", "Thu": "周四", "Fri": "周五", "Sat": "周六", "Sun": "周日"}
        shifts = {"morning": "早班", "evening": "晚班"}
        scope = "、".join(days[d] for d in constraint.days) + ("全天合计" if constraint.scope == "DAY" else "、".join(shifts[v] for v in constraint.shifts))
        bounds = (f"恰好 {constraint.min_count} 人" if constraint.min_count is not None and constraint.min_count == constraint.max_count else
            "，".join(f"{label} {value} 人" for label, value in (("至少", constraint.min_count), ("目标", constraint.target_count), ("最多", constraint.max_count)) if value is not None))
        lines.append(f"{scope}：{bounds}。")
    for index, item in enumerate(state.conditions, 1):
        lines.append(f"{index}. " + format_conditions([c.model_dump(mode="json") for c in item.changes]).replace("- ", "").replace("\n", "；"))
    if state.proposals:
        lines.append(f"另有 {len(state.proposals)} 项分析提案，尚未采纳：")
        for item in state.proposals:
            lines.append(format_conditions([c.model_dump(mode="json") for c in item.changes]))
    if state.pending:
        lines.append("待补信息：" + "；".join(f"{p.employee_id or '待选员工'}：{'、'.join(p.missing())}" for p in state.pending))
    lines.extend(item["message"] for item in state.conflicts)
    lines.extend(state.warnings)
    return "\n".join(lines)


def dependencies(service, week, current, state):
    base = current.get("confirmed")
    context = service.tools.scheduling.context_builder.build(week,
        base_schedule=Schedule.model_validate(base["schedule"]) if base else None,
        changes=unique_changes(state.current()), allow_history_bootstrap=False,
        allow_ephemeral_known_empty=True)
    return {"base_schedule_id": (base or {}).get("schedule_id"),
        "base_version": (base or {}).get("version"),
        "employee_revision": service.employees.list_with_revision()[1],
        "employees_hash": digest([e.model_dump(mode="json") for e in context.employees]),
        "rules_hash": digest(context.rules.model_dump(mode="json")),
        "conditions_hash": digest([c.model_dump(mode="json") for c in state.current()]),
        "staffing_hash": digest([state.staffing_constraints, state.proposed_staffing]),
        "history_id": context.history_schedule_id, "history_version": context.history_schedule_version,
        "history_hash": digest([h.model_dump(mode="json") for h in context.previous_days])}


def suggestions(service, week, current, state, source_message_id, deps):
    """Concrete, independently validated swaps with measured workload improvement."""
    base = current.get("confirmed") or current.get("display")
    set_id = "set_" + uuid4().hex
    result = {"suggestion_set_id": set_id, "source_message_id": source_message_id,
              "target_week": week.isoformat(), "dependencies": deps, "suggestions": []}
    if not base:
        return result
    schedule = Schedule.model_validate(base["schedule"])
    employees = service.employees.list()
    counts = Counter(a.employee_id for a in schedule.assignments)
    before = sum(counts[e.id] ** 2 for e in employees)
    context = service.tools.scheduling.context_builder.build(week, base_schedule=schedule,
        changes=unique_changes(state.current()), allow_history_bootstrap=False,
        staffing_constraints=state.proposed_staffing if state.proposed_staffing is not None else state.staffing_constraints)
    tried = set()
    for assignment in sorted(schedule.assignments, key=lambda a: -counts[a.employee_id]):
        for employee in sorted(employees, key=lambda e: (counts[e.id], e.id)):
            if counts[assignment.employee_id] - counts[employee.id] < 2:
                continue
            pair = (assignment.employee_id, employee.id)
            if pair in tried:
                continue
            replacement = Assignment(employee_id=employee.id, day=assignment.day, shift=assignment.shift)
            candidate = schedule.model_copy(update={"assignments": [a for a in schedule.assignments if a != assignment] + [replacement]})
            validation = service.tools.scheduling.validator.validate(candidate, employees, context=context)
            if not validation.valid:
                continue
            changes = [ScheduleChange(employee_id=assignment.employee_id, type="unassign", day=assignment.day, shift=assignment.shift),
                       ScheduleChange(employee_id=employee.id, type="assign", day=assignment.day, shift=assignment.shift)]
            proposal = Condition(changes=changes, source_message_id=source_message_id)
            preview = service.tools.scheduling.preview_scenario(week_start=week,
                patches=patches_for(state.current() + [proposal]), base_schedule=schedule,
                staffing_constraints=state.proposed_staffing if state.proposed_staffing is not None else state.staffing_constraints)
            if not preview.get("strict_feasible"):
                continue
            after_counts = counts.copy()
            after_counts[assignment.employee_id] -= 1
            after_counts[employee.id] += 1
            after = sum(after_counts[e.id] ** 2 for e in employees)
            sid = "sug_" + uuid4().hex
            result["suggestions"].append({"id": sid, "suggestion_id": sid,
                "suggestion_set_id": set_id, "ordinal": len(result["suggestions"]) + 1,
                "source_message_id": source_message_id, "target_week": week.isoformat(),
                "based_on_schedule_id": base["schedule_id"], "based_on_version": base["version"],
                "based_on_scenario_revision": state.scenario_revision,
                "dependencies": deps, "dependency_type": "schedule", "executable": True,
                "feasibility": "validated", "action": "replan",
                "title": f"{assignment.employee_id} 与 {employee.id} 调整一个班次",
                "description": format_conditions([c.model_dump(mode="json") for c in changes])
                    + f"。同一基准下班次数平方和 {before} → {after}，减少 {before-after}；替换方案已通过独立校验和严格试排。",
                "proposed_changes": [c.model_dump(mode="json") for c in changes],
                "improvement": {"metric": "sum_squared_workload", "before": before, "after": after},
                "validation": validation.model_dump(mode="json")})
            tried.add(pair)
            if len(result["suggestions"]) == 2:
                return result
    return result


class DialogueAgent:
    def __init__(self, service):
        self.service = service
        self.repository = DialogueRepository(service.conversations.database)

    def finish(self, *, conversation_id, workspace, client_id, owner, user, week, state, command,
               trace, response, result=None, error=None, extra=None):
        service = self.service
        metadata = {"target_week": week.isoformat(), "dialogue_state": state.model_dump(mode="json"),
                    "turn_command": command.model_dump(mode="json"), "scenario_revision": state.scenario_revision,
                    "conditions": [c.model_dump(mode="json") for c in unique_changes(state.conditions)],
                    "tool_call_ids": [c["tool_call_id"] for c in trace], **(extra or {})}
        execution = current_execution.get()
        metadata["provider_requests"] = getattr(execution, "provider_requests", [])
        if error:
            metadata["error"] = error
        intent = "ask"
        if command.clarification or (state.pending and not (result or {}).get("schedule_id")):
            intent = "clarification"
        elif command.execution == "create_draft":
            intent = "replan" if (result or {}).get("schedule", {}).get("parent_schedule_id") else "generate"
        elif command.execution in {"preview", "analyze"}:
            intent = "what_if"
        context = {"target_week": week.isoformat(), "iso_year": week.isocalendar().year,
                   "iso_week": week.isocalendar().week, "resolution_source": "structured_dialogue"}
        fields = {"intent": intent, "mutation_requested": bool(result and result.get("schedule_id")),
                  "context": context, "tool_calls": trace, "schedule_result": result,
                  "dialogue_state": state.model_dump(mode="json"), **({"error": error} if error else {})}
        return service.conversations.finalize_turn(conversation_id, workspace,
            client_message_id=client_id, owner_token=owner, content=response, intent=intent,
            mutation_requested=fields["mutation_requested"], target_week=week, metadata=metadata,
            conversation_summary=f"目标周 {week.isoformat()}；{describe(state)}"[:1400], result_fields=fields)

    def handle(self, *, conversation_id, workspace, client_id, owner, user, text,
               current_week_start, prior_messages, employees, trusted_action=None, command=None):
        service = self.service
        if trusted_action and not trusted_action.suggestion_id:
            return None
        if trusted_action:
            command = TurnCommand(reference="suggestion", suggestion_id=trusted_action.suggestion_id,
                suggestion_set_id=trusted_action.suggestion_set_id, adopt=True,
                target_week=trusted_action.target_week,
                execution={"record": "none", "preview": "preview", "create_draft": "create_draft"}[trusted_action.execution or "record"])
        if command is None or command.domain != "scheduling":
            return None
        route = AgentRouter.from_command(command)
        target = service.week_resolver.resolve(content="", route=route, current_week_start=current_week_start,
            recent_messages=prior_messages, trusted_week=trusted_action.target_week if trusted_action else None)
        week = target.week_start
        state = self.repository.get(conversation_id, week)
        before = state.model_copy(deep=True)
        # Pure factual queries use the read tools through a projection of this SAME plan.
        if (command.read_query and not command.edits and not command.staffing_constraints
                and command.reference != "suggestion" and not command.inspect and not command.clarification
                and command.execution in {"analyze", "advice"}):
            return None
        if command.reference == "suggestion" and not state.suggestion_sets:
            if command.edits or command.staffing_constraints or command.staffing_operation != "merge" or command.force_generate:
                command.clarification = "旧建议不能同时携带新条件或授权，请先单独采纳建议。"
            if not command.clarification:
                return None  # Legacy persisted cards retain their version-checked executor.
        if command.clarification:
            return self.finish(conversation_id=conversation_id, workspace=workspace, client_id=client_id,
                owner=owner, user=user, week=week, state=state, command=command, trace=[],
                response=command.clarification)
        trace = []
        service.conversations.annotate_user_message(conversation_id, workspace, user["message_id"],
            intent="generate" if command.execution == "create_draft" else "what_if",
            mutation_requested=bool(command.edits), target_week=week, owner_token=owner)

        def commit(result=None):
            nonlocal state
            with execution_stage("state_reduce"):
                state = self.repository.commit(conversation_id, workspace, week, state,
                    expected_revision=state.revision, message_id=user["message_id"], owner_token=owner,
                    command=command.model_dump(mode="json"), result=result)

        def run(name, inputs, fn):
            call = service.conversations.add_tool_call(conversation_id, workspace,
                message_id=user["message_id"], tool_name=name, input_json=inputs, owner_token=owner)
            try:
                with execution_stage("tool"):
                    output = fn()
            except Exception:
                service.conversations.finish_tool_call(call["tool_call_id"], conversation_id, workspace,
                    status="failed", output_json={"error": "operation_failed"}, owner_token=owner)
                raise
            trace.append(service.conversations.finish_tool_call(call["tool_call_id"], conversation_id, workspace,
                status="completed", output_json=output, owner_token=owner))
            return output

        current = service.tools.get_current_schedule(target_week=week)
        deps = dependencies(service, week, current, state)
        extra = {}
        if command.reference == "suggestion":
            sets = state.suggestion_sets
            selected_set = next((s for s in sets if s["suggestion_set_id"] == command.suggestion_set_id), None) if command.suggestion_set_id else None
            if command.suggestion_id:
                found = [(s, i) for s in sets for i in s["suggestions"] if i["suggestion_id"] == command.suggestion_id
                         and (selected_set is None or s == selected_set)]
                selected_set, suggestion = found[0] if len(found) == 1 else (None, None)
            else:
                selected_set = selected_set or (sets[-1] if sets else None)
                items = selected_set["suggestions"] if selected_set else []
                index = (command.suggestion_ordinal or 0) - 1
                suggestion = items[index] if 0 <= index < len(items) else None
            if not suggestion:
                command.clarification = "找不到你引用的建议；请指定当前周已展示的建议。"
            elif suggestion["dependencies"] != deps:
                command.clarification = "该建议的排班、员工、规则或历史基准已变化，请重新分析后采纳。"
                extra["error"] = {"code": "suggestion_stale"}
            elif command.adopt:
                exists = next((c for c in state.conditions if c.suggestion_id == suggestion["suggestion_id"]), None)
                if "replacement_conditions" in suggestion:
                    state.conditions = [Condition.model_validate(c) for c in suggestion["replacement_conditions"]]
                    state.proposals = [Condition.model_validate(c) for c in suggestion["replacement_proposals"]]
                    remaining = {c.id for c in state.conditions + state.proposals}
                    state.context_ids = [i for i in state.context_ids if i in remaining]
                    state.focus = Focus(kind="condition", ids=state.context_ids) if state.context_ids else None
                elif not exists:
                    item = Condition(changes=[ScheduleChange.model_validate(c) for c in suggestion["proposed_changes"]],
                        source_message_id=user["message_id"], source_kind="suggestion", suggestion_id=suggestion["suggestion_id"])
                    state.conditions.append(item)
                    state.context_ids.append(item.id)
                    state.focus = Focus(kind="condition", ids=[item.id])
                extra["referenced_suggestion"] = suggestion
            else:
                extra["referenced_suggestion"] = suggestion
        state, question = reduce_command(state, command, message_id=user["message_id"],
            employees=employees, employee_revision=deps["employee_revision"])
        if command.clarification:
            return self.finish(conversation_id=conversation_id, workspace=workspace, client_id=client_id,
                owner=owner, user=user, week=week, state=before, command=command, trace=trace,
                response=command.clarification)
        detect_conflicts(state, employees)
        # Persist complete state and commit receipt before any slow computation.
        commit()
        deps = dependencies(service, week, current, state)
        result = None
        response = describe(state)
        if command.clarification or (question and not state.pending):
            response = command.clarification or question
        elif command.reference == "suggestion" and not command.adopt:
            selected = extra.get("referenced_suggestion")
            response = selected["description"] if selected else response
        elif command.execution == "create_draft" and not command.explicit_empty and (state.pending or (state.conflicts and not command.force_generate)):
            response = "当前还有待补信息或硬冲突，暂不能生成草稿。\n" + describe(state)
            extra["execution_blocked"] = "pending_or_conflict"
        elif command.execution == "create_draft":
            selected = [] if command.explicit_empty else state.conditions if command.reference == "active" else state.current()
            staffing = [] if command.explicit_empty else state.staffing_constraints
            if command.reference_ids:
                selected = [c for c in selected if c.id in command.reference_ids]
            if not selected and not state.staffing_constraints and not command.explicit_empty and not command.force_generate:
                response = "没有可明确引用的完整条件，不能按空条件重排。请先说明条件，或明确要求无附加条件生成。"
                extra["execution_blocked"] = "empty_reference"
            elif current.get("draft"):
                response = "当前周已有待确认草稿，请在工作台确认或取消后再生成。已记录条件会保留。\n" + describe(state)
                extra["execution_blocked"] = "draft_pending"
                result = {"status": "draft_pending", "existing_draft_id": current["draft"]["schedule_id"]}
                extra["error"] = {"code": "draft_pending", "status_code": 409}
            else:
                changes = unique_changes(selected)
                snapshot = [c.model_dump(mode="json") for c in selected]
                source = {"agent_conversation_id": conversation_id, "agent_client_message_id": client_id,
                    "agent_user_message_id": user["message_id"], "scenario_revision": state.scenario_revision,
                    "dialogue_revision": state.revision, "condition_snapshot": snapshot,
                    "condition_hash": digest({"conditions": snapshot, "staffing": staffing}), "dependency_hash": digest(deps), "dependencies": deps,
                    "staffing_constraints": [c.model_dump(mode="json") for c in staffing]}
                base = current.get("confirmed")
                inputs = {"target_week": week.isoformat(), "changes": [c.model_dump(mode="json") for c in changes], **source}
                guard = (conversation_id, user["message_id"], owner)
                kwargs = {"changes": changes, "prompt": "", "staffing_constraints": staffing, "metadata_extra": source, "agent_turn_guard": guard,
                          "before_commit": lambda: service.conversations.renew_turn(conversation_id, workspace,
                              message_id=user["message_id"], owner_token=owner)}
                if command.force_generate:
                    from ..models import ForceRequest
                    from .agent_service import _format_force_violations_message
                    force = ForceRequest(requested_overrides=command.requested_overrides,
                        forced_assignments=command.forced_assignments, authorization_reason=command.authorization_reason)
                    result = run("force_generate_schedule", {**inputs, "force_request": force.model_dump(mode="json")},
                        lambda: service.tools.scheduling.force_generate(week_start=week, force_request=force,
                            changes=changes, staffing_constraints=staffing,
                            minimize_changes=command.minimize_changes, source_conversation_id=conversation_id,
                            source_message_id=user["message_id"], client_message_id=client_id,
                            scenario_revision=state.scenario_revision,
                            expected_base=((base or {}).get("schedule_id"), (base or {}).get("version")),
                            metadata_extra=source, before_commit=kwargs["before_commit"], agent_turn_guard=guard))
                elif base:
                    result = run("replan_schedule", inputs, lambda: service.tools.scheduling.replan(
                        base_schedule_id=base["schedule_id"], base_version=base["version"],
                        minimize_changes=state.minimize_changes, **kwargs))
                else:
                    result = run("generate_schedule", inputs, lambda: service.tools.scheduling.generate(week_start=week, **kwargs))
                if result.get("status") == "feasible":
                    state.last_draft = {"scenario_revision": state.scenario_revision, "schedule_id": result["schedule_id"],
                                        "version": result["version"], "condition_hash": source["condition_hash"]}
                    extra.update(generated_draft_id=result["schedule_id"], generated_draft_version=result["version"])
                    response = f"已按 {len(selected) + len(staffing)} 项要求生成草稿 v{result['version']}。请在工作台检查后手动确认。\n" + describe(state)
                    if result.get("compliance_status") == "authorized_violations":
                        response = _format_force_violations_message(result, week.isocalendar().year, week.isocalendar().week, result["version"])
                else:
                    response = service._compose_infeasible_response(result, target_week=week) + "\n" + describe(state)
        elif command.execution in {"analyze", "preview"} and not state.pending:
            if state.conflicts:
                response = "组合条件存在以下冲突，已保留各项要求供你解决：\n" + describe(state)
            else:
                base = current.get("confirmed") or current.get("display")
                inputs = {"target_week": week.isoformat(), "scenario_revision": state.scenario_revision,
                    "dialogue_revision": state.revision, "dependency_hash": digest(deps),
                    "changes": [c.model_dump(mode="json") for c in unique_changes(state.current())]}
                result = run("preview_scenario", inputs, lambda: service.tools.scheduling.preview_scenario(
                    week_start=week, patches=patches_for(state.current()),
                    staffing_constraints=state.proposed_staffing if state.proposed_staffing is not None else state.staffing_constraints,
                    base_schedule=Schedule.model_validate(base["schedule"]) if base else None))
                # Re-read dependencies before writing a result from slow computation.
                if deps != dependencies(service, week, service.tools.get_current_schedule(target_week=week), state):
                    raise ScenarioRevisionConflict("分析期间依赖已变化，请重新试排。")
                result.update(scenario_revision=state.scenario_revision, dialogue_revision=state.revision,
                              dependency_hash=digest(deps), requested_changes=inputs["changes"])
                if result.get("suggestions"):
                    collection = {"suggestion_set_id": "set_" + uuid4().hex,
                        "source_message_id": user["message_id"], "target_week": week.isoformat(),
                        "dependencies": deps, "suggestions": []}
                    for index, suggestion in enumerate(result["suggestions"], 1):
                        repair = suggestion["scenario_patch"]
                        def repaired(items):
                            output = []
                            for item in items:
                                changes = [c for c in item.changes if not (
                                    c.employee_id == repair["employee_id"] and c.day in repair["days"]
                                    and c.type == repair["change_type"] and c.shift == repair.get("shift"))]
                                if changes:
                                    output.append(item.model_copy(update={"changes": changes}).model_dump(mode="json"))
                            return output
                        sid = "sug_" + uuid4().hex
                        suggestion.update(id=sid, suggestion_id=sid, ordinal=index,
                            suggestion_set_id=collection["suggestion_set_id"], source_message_id=user["message_id"],
                            target_week=week.isoformat(), based_on_scenario_revision=state.scenario_revision,
                            based_on_schedule_id=(base or {}).get("schedule_id"), based_on_version=(base or {}).get("version"),
                            dependencies=deps, dependency_type="scenario", executable=True, action="replan",
                            replacement_conditions=repaired(state.conditions), replacement_proposals=repaired(state.proposals))
                        collection["suggestions"].append(suggestion)
                    state.suggestion_sets.append(collection)
                    extra["suggestions"] = collection["suggestions"]
                state.last_preview = result
                extra["scenario_preview"] = result
                response = ("组合试排通过严格求解和独立校验；尚未创建草稿。" if result.get("strict_feasible") else
                            service._compose_infeasible_response(result, target_week=week)) + "\n" + describe(state)
        elif command.execution == "advice":
            collection = run("build_suggestions", {"target_week": week.isoformat(), "dependencies": deps},
                lambda: suggestions(service, week, current, state, user["message_id"], deps))
            state.suggestion_sets.append(collection)
            extra["suggestions"] = collection["suggestions"]
            response = "\n\n".join(f"{i['ordinal']}. {i['title']}\n{i['description']}" for i in collection["suggestions"]) or "在当前硬约束与基准下，没有找到已验证可改善工作量的单班替换方案。"
        if command.inspect:
            response += f"\n目标周：{week.isoformat()} 至 {(week+timedelta(days=6)).isoformat()}；" + (f"将 Replan 正式版本 v{current['confirmed']['version']}。" if current.get("confirmed") else "无正式版本，将 Generate。")
        # Result writeback is fenced and revision checked; receipt recovers a lost reply.
        commit(result={"schedule_result": result, "response": response, "extra": extra})
        error = extra.get("error")
        final = self.finish(conversation_id=conversation_id, workspace=workspace, client_id=client_id,
            owner=owner, user=user, week=week, state=state, command=command, trace=trace,
            response=response, result=result, error=error, extra=extra)
        if error:
            from .agent_service import AgentTurnError
            raise AgentTurnError(error.get("status_code", 409), error["code"], response, final)
        return final

    def recover(self, *, conversation_id, browser_workspace_id, client_message_id, user_message, owner_token):
        receipt = (user_message.get("metadata") or {}).get("dialogue_commit")
        if not receipt or receipt["command"].get("source") == "read_focus":
            return None
        from ..models.dialogue import DialogueState
        state = DialogueState.model_validate(receipt["state"])
        command = TurnCommand.model_validate(receipt["command"])
        saved = receipt.get("result") or {}
        response = saved.get("response") or ("条件状态已保存；上次执行在回复前中断，未完成的执行请重新发起。\n" + describe(state))
        return self.finish(conversation_id=conversation_id, workspace=browser_workspace_id,
            client_id=client_message_id, owner=owner_token, user=user_message,
            week=date.fromisoformat(receipt["week"]), state=state, command=command,
            trace=self.service.conversations.list_tool_calls(conversation_id, browser_workspace_id, message_id=user_message["message_id"]),
            response=response, result=saved.get("schedule_result"), extra=saved.get("extra"))
