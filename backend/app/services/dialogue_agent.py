"""Stateful scheduling orchestration with separate recording and execution contracts."""
import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from uuid import uuid4

from ..execution import current_execution, execution_stage
from ..models.dialogue import Condition, Focus, TurnCommand
from ..models.domain import Assignment, Schedule, ScheduleChange
from ..models.scenario_changes import format_conditions
from ..repository.dialogue import DialogueRepository, patches_for
from ..repository.scenarios import ScenarioRevisionConflict
from .agent_context import WeekResolutionError
from .agent_router import AgentIntent, AgentRoute
from .dialogue_parser import parse_command
from .dialogue_reducer import detect_conflicts, reduce_command, unique_changes


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def describe(state):
    lines = [f"已记录 {len(state.conditions)} 项有效要求。"]
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
        changes=unique_changes(state.current()), allow_history_bootstrap=False)
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
                patches=patches_for(state.current() + [proposal]), base_schedule=schedule)
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
        intent = "clarification" if command.clarification or state.pending else "replan" if command.execution == "create_draft" else "what_if" if command.execution in {"preview", "analyze"} else "ask"
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
               current_week_start, prior_messages, employees, trusted_action=None):
        service = self.service
        if trusted_action and not trusted_action.suggestion_id:
            return None
        if not trusted_action and re.search(r"\brepair_\d+_(?:mon|tue|wed|thu|fri|sat|sun)\b", text, re.I):
            return None
        # Force continues through the established authorization path, including H01.
        from .agent_router import AgentRouter
        if AgentRouter._explicit_authorization(text) and not re.search(r"不要强制|不强制", text):
            return None
        route = AgentRoute(intent=AgentIntent.ASK)
        prior = prior_messages
        last_ui_week = next(((m.get("metadata") or {}).get("current_week_start") for m in reversed(prior)
                             if m.get("role") == "user"), None)
        if current_week_start and last_ui_week and current_week_start.isoformat() != last_ui_week:
            prior = []
        target = service.week_resolver.resolve(content=text, route=route, current_week_start=current_week_start,
            recent_messages=prior, trusted_week=trusted_action.target_week if trusted_action else None)
        week = target.week_start
        state = self.repository.get(conversation_id, week)
        before = state.model_copy(deep=True)
        with execution_stage("agent_route"):
            command = parse_command(text, state, employees, service.llm) if not trusted_action else TurnCommand(
                reference="suggestion", suggestion_id=trusted_action.suggestion_id,
                suggestion_set_id=trusted_action.suggestion_set_id, adopt=True,
                execution={"record": "none", "preview": "preview", "create_draft": "create_draft"}[trusted_action.execution or "record"])
        candidate_query = bool(re.search(r"兼职|同时会饮品和收银", text)) and not re.search(r"E\d{2}|重排|生成|优先", text)
        if candidate_query:
            candidates = employees
            if "这里面" in text or "那个" in text:
                candidates = [e for e in employees if e.id in state.employee_focus]
            if "兼职" in text:
                candidates = [e for e in candidates if e.role in {"part_time", "part-time"}]
            if "饮品" in text:
                candidates = [e for e in candidates if "beverage" in e.skills]
            if "收银" in text:
                candidates = [e for e in candidates if "cashier" in e.skills]
            if "周末" in text:
                candidates = [e for e in candidates if any(d in e.available_days and d not in e.leave_days for d in ("Sat", "Sun"))]
            state.employee_focus = [e.id for e in candidates]
            state.focus = Focus(kind="employees", ids=state.employee_focus)
            command = TurnCommand(inspect=True)
            candidate_response = "符合员工主数据范围的候选：" + ("、".join(state.employee_focus) or "暂无") + "。"
            if len(candidates) > 1:
                candidate_response += "有多个候选，请明确选择员工后再记录排班条件。"
        else:
            candidate_response = None
        if command is None:
            # Explicit employee mentions establish a bounded referent without an action.
            focus = list(dict.fromkeys(re.findall(r"(?<![A-Za-z0-9_])E\d{2}(?![A-Za-z0-9_])", text, re.I)))
            if len(focus) == 1 and focus[0].upper() in {e.id for e in employees}:
                state.employee_focus = [focus[0].upper()]
                self.repository.commit(conversation_id, workspace, week, state,
                    expected_revision=before.revision, message_id=user["message_id"], owner_token=owner,
                    command={"execution": "none", "source": "read_focus"})
            return None
        # A persisted legacy scenario/suggestion has its own version guards and
        # response contract.  Let the established router consume those cards
        # until this conversation has a structured dialogue suggestion set.
        if command.reference == "suggestion" and not state.suggestion_sets:
            return None
        if command.explicit_empty and not state.conditions and not state.proposals and not state.pending:
            return None
        # Preserve the established single-turn scenario/analysis contract. The
        # dialogue reducer is needed once a conversation has state to carry, or
        # when the user explicitly records, defers, corrects, adopts, or fills it.
        legacy_only = all(c.source_kind == "legacy" for c in state.conditions)
        if (legacy_only and not state.proposals and not state.pending
                and command.execution in {"preview", "advice", "create_draft"}
                and command.edits and not command.adopt
                and command.source != "deterministic_action"):
            return None
        if (state.conditions and legacy_only and not state.proposals and not state.pending
                and command.edits and re.search(r"如果|改成|试排", text)):
            return None
        if command.inspect and not command.edits and not state.conditions and not state.proposals and not state.pending:
            return None
        trace = []
        service.conversations.annotate_user_message(conversation_id, workspace, user["message_id"],
            intent="replan" if command.execution == "create_draft" else "what_if",
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
                if not exists:
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
        detect_conflicts(state, employees)
        # Persist complete state and commit receipt before any slow computation.
        commit()
        result = None
        response = describe(state)
        if candidate_response:
            response = candidate_response
        elif command.clarification or (question and not state.pending):
            response = command.clarification or question
        elif command.reference == "suggestion" and not command.adopt:
            selected = extra.get("referenced_suggestion")
            response = selected["description"] if selected else response
        elif command.execution == "create_draft" and (state.pending or state.conflicts):
            response = "当前还有待补信息或硬冲突，暂不能生成草稿。\n" + describe(state)
            extra["execution_blocked"] = "pending_or_conflict"
        elif command.execution == "create_draft":
            selected = state.conditions if command.reference == "active" else state.current()
            if command.reference_ids:
                selected = [c for c in selected if c.id in command.reference_ids]
            if not selected and not command.explicit_empty:
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
                    "condition_hash": digest(snapshot), "dependency_hash": digest(deps), "dependencies": deps}
                base = current.get("confirmed")
                inputs = {"target_week": week.isoformat(), "changes": [c.model_dump(mode="json") for c in changes], **source}
                guard = (conversation_id, user["message_id"], owner)
                kwargs = {"changes": changes, "prompt": "", "metadata_extra": source, "agent_turn_guard": guard,
                          "before_commit": lambda: service.conversations.renew_turn(conversation_id, workspace,
                              message_id=user["message_id"], owner_token=owner)}
                if base:
                    result = run("replan_schedule", inputs, lambda: service.tools.scheduling.replan(
                        base_schedule_id=base["schedule_id"], base_version=base["version"],
                        minimize_changes=state.minimize_changes, **kwargs))
                else:
                    result = run("generate_schedule", inputs, lambda: service.tools.scheduling.generate(week_start=week, **kwargs))
                if result.get("status") == "feasible":
                    state.last_draft = {"scenario_revision": state.scenario_revision, "schedule_id": result["schedule_id"],
                                        "version": result["version"], "condition_hash": source["condition_hash"]}
                    extra.update(generated_draft_id=result["schedule_id"], generated_draft_version=result["version"])
                    response = f"已按 {len(selected)} 项要求（{len(changes)} 个原子条件）生成草稿 v{result['version']}。请在工作台检查后手动确认。\n" + describe(state)
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
                result = run("preview_dialogue", inputs, lambda: service.tools.scheduling.preview_scenario(
                    week_start=week, patches=patches_for(state.current()),
                    base_schedule=Schedule.model_validate(base["schedule"]) if base else None))
                # Re-read dependencies before writing a result from slow computation.
                if deps != dependencies(service, week, service.tools.get_current_schedule(target_week=week), state):
                    raise ScenarioRevisionConflict("分析期间依赖已变化，请重新试排。")
                result.update(scenario_revision=state.scenario_revision, dialogue_revision=state.revision,
                              dependency_hash=digest(deps), requested_changes=inputs["changes"])
                state.last_preview = result
                extra["scenario_preview"] = result
                response = ("组合试排通过严格求解和独立校验；尚未创建草稿。" if result.get("strict_feasible") else
                            service._compose_infeasible_response(result, target_week=week)) + "\n" + describe(state)
        elif command.execution == "advice":
            existing = state.suggestion_sets[-1] if state.suggestion_sets and "拆成" in text else None
            collection = existing or run("build_suggestions", {"target_week": week.isoformat(), "dependencies": deps},
                lambda: suggestions(service, week, current, state, user["message_id"], deps))
            if not existing:
                state.suggestion_sets.append(collection)
            extra["suggestions"] = collection["suggestions"]
            response = "\n\n".join(f"{i['ordinal']}. {i['title']}\n{i['description']}" for i in collection["suggestions"]) or "在当前硬约束与基准下，没有找到已验证可改善工作量的单班替换方案。"
        if command.inspect and "目标周" in text:
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
