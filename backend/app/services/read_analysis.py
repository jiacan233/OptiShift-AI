"""Pure analyses: no repository, persistence, scenario or confirmation capability."""
from __future__ import annotations

from collections import Counter

from ..models import Assignment, Day, HistoryStatus, Schedule, SchedulingContext, SHIFTS, WEEK_DAYS
from ..validator.rule_validator import RuleValidator
from .read_query import ReadQueryPlan


def validate_snapshot(schedule: Schedule, context: SchedulingContext) -> dict:
    missing_history = context.history_status is HistoryStatus.UNAVAILABLE
    # Local rules remain measurable without inventing a previous-week boundary.
    local = context.model_copy(deep=True)
    if missing_history:
        local.history_status = HistoryStatus.KNOWN_EMPTY
        local.previous_days = []
    result = RuleValidator().validate(schedule, local.employees, local).model_dump(mode="json")
    result["history_status"] = context.history_status.value
    result["unknown_rules"] = ["R06", "R07"] if missing_history else []
    if missing_history:
        result["valid"] = None
        for rule in result["unknown_rules"]:
            result["hard_constraints"][rule]["passed"] = None
    return result


def analyze_snapshot(schedule: Schedule, context: SchedulingContext, plan: ReadQueryPlan) -> dict:
    validation = validate_snapshot(schedule, context)
    employees = {e.id: e for e in context.employees}
    keys = {(a.employee_id, a.day, a.shift) for a in schedule.assignments if a.employee_id in employees}
    workload = Counter(key[0] for key in keys)
    slots = []
    for day in ([plan.day] if plan.day else WEEK_DAYS):
        for shift in ([plan.shift] if plan.shift else SHIFTS):
            ids = sorted(eid for eid, d, s in keys if d == day and s == shift)
            minimum = context.rules.minimum_staff(day, shift)
            facts = {
                "day": day.value, "shift": shift.value, "actual_staff": len(ids),
                "minimum_staff": minimum, "excess_staff": max(0, len(ids) - minimum),
                "assignments": [{"employee_id": eid, "role": employees[eid].role,
                                 "skills": [s.value for s in employees[eid].skills]} for eid in ids],
            }
            for skill in ("manager", "beverage", "cashier"):
                actual = sum(skill in {s.value for s in employees[eid].skills} for eid in ids)
                required = getattr(context.rules, f"{skill}_per_shift")
                facts[skill] = {"actual": actual, "required": required, "passed": actual >= required}
            facts["validation"] = {"coverage": [c for c in validation["coverage"] if c["day"] == day.value and c["shift"] == shift.value]}
            slots.append(facts)
    employee_facts = []
    for eid in plan.employee_ids:
        employee = employees[eid]
        assignments = [a.model_dump(mode="json") for a in schedule.assignments if a.employee_id == eid
                       and (plan.day is None or a.day == plan.day) and (plan.shift is None or a.shift == plan.shift)]
        employee_facts.append({
            **employee.model_dump(mode="json"), "assignments": assignments, "weekly_shifts": workload[eid],
            "requested_changes": [c.model_dump(mode="json") for c in context.requested_changes if c.employee_id == eid],
            "violations": [v for v in validation["violations"] if v["employee_id"] == eid],
            "unique_necessity_proven": False,
        })
    return {
        "status": "analyzed", "target_week": schedule.week_start.isoformat(),
        "schedule_id": schedule.schedule_id, "version": schedule.version,
        "schedule_status": schedule.status.value, "source": "explicit_version" if plan.version else "display_schedule",
        "slots": slots, "employees": employee_facts,
        "workload": {eid: workload[eid] for eid in sorted(employees)},
        "rules": context.rules.model_dump(mode="json"), "rules_source": "current_rule_config", "validation": validation,
        "read_only": True,
    }


def counterfactual_snapshot(schedule: Schedule, context: SchedulingContext, plan: ReadQueryPlan) -> dict:
    result = analyze_snapshot(schedule, context, plan)
    if plan.day is None:
        result["clarification"] = "请指定要移除人员的日期；未指定班次时会分别分析早晚班。"
        result["counterfactuals"] = []
        return result
    targets = sorted({(a.employee_id, a.day, a.shift) for a in schedule.assignments
                      if a.day == plan.day and (plan.shift is None or a.shift == plan.shift)
                      and (not plan.employee_ids or a.employee_id in plan.employee_ids)})
    analyses = []
    for eid, day, shift in targets:
        copied = schedule.model_copy(deep=True)
        copied.assignments = [a for a in copied.assignments if (a.employee_id, a.day, a.shift) != (eid, day, shift)]
        validation = validate_snapshot(copied, context)
        slot_violations = [v for v in validation["violations"] if v["day"] == day.value and v["shift"] == shift.value]
        slot_passed = all(c["passed"] for c in validation["coverage"] if c["day"] == day.value and c["shift"] == shift.value)
        replacements = []
        occupied = {a.employee_id for a in copied.assignments if a.day == day}
        for employee in context.employees:
            if employee.id == eid or employee.id in occupied:
                continue
            alternative = copied.model_copy(deep=True)
            alternative.assignments.append(Assignment(employee_id=employee.id, day=day, shift=shift))
            if validate_snapshot(alternative, context)["valid"] is True:
                replacements.append(employee.id)
        analyses.append({
            "employee_id": eid, "day": day.value, "shift": shift.value,
            "direct_removal_slot_passed": slot_passed,
            "direct_removal_valid": validation["valid"], "violations": validation["violations"],
            "slot_violations": slot_violations, "replacement_needed_for_slot": not slot_passed,
            "replacement_employee_ids": replacements, "multiple_replacements": len(replacements) > 1,
            "re_solve_status": "not_run", "re_solve_feasible": None,
            "unique_necessity_proven": False,
            "necessity": "not_necessary" if validation["valid"] is True or replacements else "unproven",
            "workload_delta": {eid: -1}, "objective_delta": None,
            "objective_note": "未重新求解或比较目标值；不能据此断言唯一必要。",
        })
    result["counterfactuals"] = analyses
    if not targets:
        result["clarification"] = "所选员工在指定日期和班次没有可移除的 assignment。"
    return result
