"""Pure reduction; all references are resolved before a single state commit."""
from copy import deepcopy

from ..models.dialogue import Condition, DialogueState, Focus, PendingAction
from ..models.domain import ChangeType, ScheduleChange


class DialogueClarification(ValueError):
    pass


def key(change):
    return change.employee_id, change.day, change.type, change.shift


def unique_changes(conditions):
    values = {key(c): c for item in conditions for c in item.changes}
    return sorted(values.values(), key=lambda c: tuple(str(x or "") for x in key(c)))


def _selected(state, edit):
    items = state.conditions + state.proposals
    if edit.reference_ids:
        selected = [item for item in items if item.id in edit.reference_ids]
        if len(selected) != len(set(edit.reference_ids)):
            raise DialogueClarification("引用的条件已经失效，请重新指定。")
        return selected
    if edit.operation == "correct" or (not edit.employee_ids and not edit.days and not edit.type):
        if state.focus and state.focus.kind in {"condition", "proposal"}:
            return [item for item in items if item.id in state.focus.ids]
        return []
    return [item for item in items if any(
        (not edit.employee_ids or c.employee_id in edit.employee_ids)
        and (not edit.days or c.day in edit.days)
        and (not edit.type or c.type == edit.type)
        and (not edit.shift or c.shift == edit.shift) for c in item.changes)]


def reduce_command(original, command, *, message_id, employees, employee_revision):
    state = original.model_copy(deep=True)
    known = {e.id: e for e in employees}
    if command.clarification:
        return state, command.clarification
    if command.minimize_changes:
        state.minimize_changes = True
    try:
        for edit in command.edits:
            if set(edit.employee_ids) - known.keys():
                raise DialogueClarification("员工主数据中不存在：" + "、".join(set(edit.employee_ids) - known.keys()))
            if edit.operation == "cancel_pending":
                state.tombstones.extend(p.id for p in state.pending)
                state.pending = []
                if state.focus and state.focus.kind == "pending":
                    state.focus = None
                continue
            if edit.operation in {"correct", "remove"}:
                candidates = _selected(state, edit)
                if len(candidates) != 1:
                    raise DialogueClarification(
                        "没有找到符合范围的临时条件；员工档案未改变。" if not candidates else
                        "找到多条符合范围的条件，请指定要撤销或纠正的那一条。")
                item = candidates[0]
                if edit.operation == "remove":
                    state.conditions = [c for c in state.conditions if c.id != item.id]
                    state.proposals = [c for c in state.proposals if c.id != item.id]
                    state.context_ids = [cid for cid in state.context_ids if cid != item.id]
                    state.tombstones.append(item.id)
                    state.focus = None
                else:
                    if edit.old_day and not any(c.day == edit.old_day for c in item.changes):
                        raise DialogueClarification("当前焦点条件与要纠正的旧日期不一致，请指明条件。")
                    item.changes = [c.model_copy(update={
                        **({"day": edit.days[0]} if edit.days else {}),
                        **({"shift": edit.shift} if edit.shift else {}),
                    }) if not edit.old_day or c.day == edit.old_day else c for c in item.changes]
                    item.source_message_id = message_id
                continue
            if edit.operation == "focus":
                state.employee_focus = edit.employee_ids
                state.focus = Focus(kind="employees", ids=edit.employee_ids)
                continue
            if edit.operation == "adopt":
                command.reference_ids.extend(edit.reference_ids)
                command.adopt = True
                continue
            member_ids = list(edit.employee_ids)
            if edit.group_skill:
                member_ids = [e.id for e in employees if edit.group_skill in [s.value for s in e.skills]]
                if not member_ids:
                    raise DialogueClarification("员工主数据中没有符合该技能范围的员工。")
            if not member_ids and len(state.employee_focus) == 1:
                member_ids = list(state.employee_focus)
            # An unrelated incomplete request never overwrites an existing action.
            compatible = [p for p in state.pending if (not member_ids or not p.employee_id or p.employee_id in member_ids)
                          and (not edit.type or not p.type or p.type == edit.type)]
            filling = compatible[0] if len(compatible) == 1 else None
            if len(compatible) > 1 and (not edit.days or not edit.type):
                raise DialogueClarification("有多个待补动作，请指定本次补充对应哪一个员工或动作。")
            if not edit.type and not edit.days and not edit.shift and member_ids and not filling:
                state.employee_focus = member_ids
                state.focus = Focus(kind="employees", ids=member_ids)
                continue
            actions = []
            for employee_id in member_ids or [None]:
                pending = deepcopy(filling) if filling else PendingAction(source_message_id=message_id)
                pending.employee_id = employee_id or pending.employee_id
                pending.type = edit.type or pending.type
                pending.days = edit.days or pending.days
                pending.shift = edit.shift or pending.shift
                pending.proposal = edit.proposal if edit.type else pending.proposal
                actions.append(pending)
            complete_changes = []
            for pending in actions:
                if pending.missing():
                    state.pending = [p for p in state.pending if p.id != pending.id] + [pending]
                    state.focus = Focus(kind="pending", ids=[pending.id])
                    if pending.employee_id:
                        state.employee_focus = [pending.employee_id]
                    continue
                complete_changes.extend(ScheduleChange(employee_id=pending.employee_id, type=pending.type,
                    day=day, shift=pending.shift) for day in pending.days)
                state.pending = [p for p in state.pending if p.id != pending.id]
            if complete_changes:
                existing = next((i for i in state.conditions + state.proposals
                                 if set(map(key, i.changes)) == set(map(key, complete_changes))), None)
                if existing:
                    item = existing
                    if not edit.proposal and item in state.proposals:
                        state.proposals.remove(item)
                        state.conditions.append(item)
                        item.source_message_id = message_id
                else:
                    item = Condition(changes=complete_changes, source_message_id=message_id,
                                     employee_revision=employee_revision if edit.group_skill else None)
                    (state.proposals if edit.proposal else state.conditions).append(item)
                state.employee_focus = list(dict.fromkeys(c.employee_id for c in item.changes))
                state.focus = Focus(kind="proposal" if item in state.proposals else "condition", ids=[item.id])
                if item.id not in state.context_ids:
                    state.context_ids.append(item.id)
        if command.reference == "active":
            selected = state.conditions
        elif command.reference_ids:
            selected = [i for i in state.conditions + state.proposals if i.id in command.reference_ids]
            if len(selected) != len(set(command.reference_ids)):
                raise DialogueClarification("部分引用已失效，不能继续执行。")
        else:
            selected = state.current()
        if command.expected_count is not None and command.expected_count != len(selected):
            raise DialogueClarification(f"当前可明确定位 {len(selected)} 项要求，与你说的 {command.expected_count} 项不一致，请明确引用范围。")
        if command.adopt or command.execution == "create_draft":
            adopted = [p for p in state.proposals if p.id in {s.id for s in selected}]
            state.conditions.extend(adopted)
            state.proposals = [p for p in state.proposals if p not in adopted]
            if state.focus and state.focus.kind == "proposal" and any(p.id in state.focus.ids for p in adopted):
                state.focus.kind = "condition"
    except DialogueClarification as exc:
        # An invalid batch cannot partially remove, correct or adopt conditions.
        return original.model_copy(deep=True), str(exc)
    question = None
    if state.pending:
        question = "待补信息：" + "；".join(
            f"{p.employee_id or '待选员工'}：{'、'.join(p.missing())}" for p in state.pending)
    return state, question


def detect_conflicts(state: DialogueState, employees):
    changes = unique_changes(state.current())
    conflicts, warnings = [], []
    for employee in employees:
        for day in {c.day for c in changes if c.employee_id == employee.id}:
            scoped = [c for c in changes if c.employee_id == employee.id and c.day == day]
            assigned = [c for c in scoped if c.type == ChangeType.ASSIGN]
            if len({c.shift for c in assigned}) > 1:
                conflicts.append({"code": "H01", "employee_id": employee.id, "day": day.value,
                                  "message": f"{employee.id} {day.value} 不能同日安排两个班次（H01 不可授权突破）。"})
            for c in scoped:
                unavailable = day not in employee.available_days or day in employee.leave_days
                unavailable = unavailable or any(x.type in {ChangeType.LEAVE, ChangeType.UNAVAILABLE}
                                                and x.shift in {None, c.shift} for x in scoped)
                if any(x.type == ChangeType.AVAILABLE and x.shift in {None, c.shift} for x in scoped):
                    unavailable = False
                if c.type == ChangeType.ASSIGN and unavailable:
                    conflicts.append({"code": "availability_conflict", "employee_id": employee.id, "day": day.value,
                        "message": f"{employee.id} {day.value} 的请假/不可用与安排上班冲突。请取消对应限制或撤销安排。"})
                if c.type == ChangeType.ASSIGN and any(x.type == ChangeType.UNASSIGN and x.shift == c.shift for x in scoped):
                    conflicts.append({"code": "assignment_conflict", "employee_id": employee.id, "day": day.value,
                        "message": f"{employee.id} {day.value} 同一班次同时要求安排和移出。"})
                if c.type == ChangeType.PREFERENCE and unavailable:
                    warnings.append(f"{employee.id} {day.value} 的偏好遇到硬不可用，偏好不能覆盖该限制。")
    state.conflicts, state.warnings = conflicts, warnings
    return conflicts
