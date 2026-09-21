"""Canonical scenario conversion and reduction, shared by preview and application."""

from collections import Counter

from .domain import ChangeType, PatchOperation, ScenarioPatch, ScheduleChange


def scenario_patch_to_schedule_changes(patch: ScenarioPatch) -> list[ScheduleChange]:
    days = patch.days or patch.candidate_days
    return [
        ScheduleChange(
            employee_id=patch.employee_id,
            type=patch.change_type,
            day=day,
            shift=patch.shift,
            work_day_count=patch.work_day_count,
            candidate_days=patch.candidate_days,
            shift_mode=patch.shift_mode,
            day_selection_mode=patch.day_selection_mode,
            work_day_count_mode=patch.work_day_count_mode,
        )
        for day in days
    ]


def scenario_patches_to_schedule_changes(patches: list[ScenarioPatch]) -> list[ScheduleChange]:
    return [
        change
        for patch in patches
        if patch.operation != PatchOperation.CLEAR
        for change in scenario_patch_to_schedule_changes(patch)
    ]


def schedule_change_to_scenario_patch(change: ScheduleChange, operation="add") -> ScenarioPatch:
    change_type = (
        ChangeType.LEAVE
        if operation == "remove" and change.type == ChangeType.AVAILABLE
        else change.type
    )
    return ScenarioPatch(
        employee_id=change.employee_id,
        change_type=change_type,
        days=[change.day] if change.day else [],
        shift=change.shift,
        operation=operation,
        work_day_count=change.work_day_count,
        candidate_days=change.candidate_days,
        shift_mode=change.shift_mode,
        day_selection_mode=change.day_selection_mode,
        work_day_count_mode=change.work_day_count_mode,
    )


def route_scenario_patches(changes, operations=None, operation="add") -> list[ScenarioPatch]:
    """Ordered operations win; a supplied legacy projection must agree in full."""
    if operations:
        projected = [
            ScheduleChange(
                employee_id=item["employee_id"],
                type=item["type"],
                day=item.get("day"),
                shift=item.get("shift"),
            )
            for item in operations
            if item.get("operation", operation) != "clear"
        ]

        def key(c):
            return c.employee_id, c.type, c.day, c.shift

        if changes and Counter(map(key, changes)) != Counter(map(key, projected)):
            raise ValueError("排班条件与操作不一致，请重新说明员工、日期和班次。")
        patches = []
        for item in operations:
            op = item.get("operation", operation)
            if op == "clear":
                patches.append(
                    ScenarioPatch(
                        employee_id=item["employee_id"],
                        operation=op,
                        change_type=item.get("type", "leave"),
                        shift=item.get("shift"),
                        days=[item["day"]] if item.get("day") else [],
                    )
                )
            else:
                change = ScheduleChange(
                    employee_id=item["employee_id"],
                    type=item["type"],
                    day=item["day"],
                    shift=item.get("shift"),
                )
                patches.append(schedule_change_to_scenario_patch(change, op))
    else:
        patches = [schedule_change_to_scenario_patch(change, operation) for change in changes]
    # A multi-day SET replaces one constraint with the complete day set, not
    # sequential singleton SETs (which would keep only the last day).
    grouped = []
    for patch in patches:

        def identity(p):
            return p.employee_id, p.change_type, p.shift, p.operation

        if grouped and identity(grouped[-1]) == identity(patch):
            grouped[-1] = grouped[-1].model_copy(
                update={"days": list(dict.fromkeys(grouped[-1].days + patch.days))}
            )
        else:
            grouped.append(patch)
    return grouped


def apply_scenario_patch(patches: list[ScenarioPatch], patch: ScenarioPatch) -> list[ScenarioPatch]:
    def matches(item):
        if patch.operation == PatchOperation.CLEAR:
            return item.employee_id == patch.employee_id
        if patch.operation == PatchOperation.SET:
            return item.employee_id == patch.employee_id and item.change_type == patch.change_type
        return (
            item.employee_id == patch.employee_id
            and item.change_type == patch.change_type
            and item.shift == patch.shift
        )

    if patch.operation == PatchOperation.CLEAR:
        result = []
        for item in patches:
            if not matches(item):
                result.append(item)
            elif patch.days:
                days = [day for day in item.days if day not in patch.days]
                if days:
                    result.append(item.model_copy(update={"days": days}))
        return result
    matching = [item for item in patches if matches(item)]
    current_days = list(dict.fromkeys(day for item in matching for day in item.days))
    if patch.operation == PatchOperation.SET:
        days = list(patch.days)
    elif patch.operation in {PatchOperation.REMOVE, PatchOperation.CLEAR}:
        days = [day for day in current_days if day not in patch.days]
    else:
        days = list(dict.fromkeys(current_days + patch.days))
    result = [item for item in patches if not matches(item)]
    if days:
        result.append(patch.model_copy(update={"operation": PatchOperation.ADD, "days": days}))
    return result


def apply_scenario_patches(
    patches: list[ScenarioPatch], incoming: list[ScenarioPatch]
) -> list[ScenarioPatch]:
    previous_set = None
    for patch in incoming:
        scope = (patch.employee_id, patch.change_type)
        is_set = patch.operation == PatchOperation.SET
        effective = (
            patch.model_copy(update={"operation": PatchOperation.ADD})
            if is_set and previous_set == scope
            else patch
        )
        patches = apply_scenario_patch(patches, effective)
        previous_set = scope if is_set else None
    return patches


def build_scenario_preview_inputs(route, *, conversation_id, target_week, expected_revision=None):
    operations = canonical_conditions(route)
    route_scenario_patches(route.changes, operations, route.operation)
    return {
        "conversation_id": conversation_id,
        "target_week": target_week,
        "changes": list(route.changes),
        "operations": operations,
        "employee_ids": list(route.employees),
        "operation": route.operation,
        "expected_revision": expected_revision,
    }


def canonical_conditions(route) -> list[dict]:
    if route.operations:
        return [item.model_dump(mode="json") for item in route.operations]
    return [
        {**item.model_dump(mode="json"), "operation": route.operation} for item in route.changes
    ]


def format_conditions(conditions: list[dict]) -> str:
    days = {
        "Mon": "周一",
        "Tue": "周二",
        "Wed": "周三",
        "Thu": "周四",
        "Fri": "周五",
        "Sat": "周六",
        "Sun": "周日",
    }
    shifts = {"morning": "早班", "evening": "晚班"}
    kinds = {
        "leave": "请假",
        "unavailable": "不可用",
        "available": "可用",
        "preference": "优先",
        "assign": "安排上班",
        "unassign": "取消班次",
    }
    lines = []
    seen_groups = set()
    for c in conditions:
        cand = c.get("candidate_days") or []
        count = c.get("work_day_count")
        emp = c["employee_id"]
        if cand and count:
            group_key = (emp, tuple(cand), count, c.get("type"))
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            cand_str = "、".join(days.get(d, d) for d in cand)
            shift_str = shifts.get(c.get("shift"), "班次自选" if c.get("shift") is None else "")
            lines.append(f"- {emp} {cand_str}任选{count}天{shift_str}{kinds.get(c.get('type', ''), '')}")
            continue

        prefix = (
            "移除条件："
            if c.get("operation") == "remove"
            else "替换条件："
            if c.get("operation") == "set"
            else "清空条件："
            if c.get("operation") == "clear"
            else ""
        )
        day_str = days.get(c.get("day"), "")
        shift_str = shifts.get(c.get("shift"), "班次自选" if c.get("shift") is None and c.get("type") == "assign" else "")
        lines.append("- " + prefix + f"{c['employee_id']} {day_str}{shift_str}{kinds.get(c.get('type', ''), '')}")
    return "\n".join(lines)
