"""Independent acceptance-path validation for final schedules."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ..core import SchedulingFacts
from ..execution import traced
from ..models import (
    SHIFTS,
    WEEK_DAYS,
    Day,
    Employee,
    HistoryStatus,
    RuleCheck,
    RuleConfig,
    RuleViolation,
    Schedule,
    SchedulingContext,
    Shift,
    Skill,
    ValidationResult,
)

HARD_RULE_IDS: tuple[str, ...] = (
    "H01",
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R06",
    "R07",
    "R08",
    "R09",
)


class RuleValidator:
    """Recompute every hard rule without consulting solver variables."""

    @traced("validator")
    def validate(
        self,
        schedule: Schedule,
        employees: list[Employee],
        context: SchedulingContext | None = None,
        rules: RuleConfig | None = None,
    ) -> ValidationResult:
        effective_rules = rules or (context.rules if context is not None else RuleConfig())
        if context is None:
            effective_context = SchedulingContext(
                employees=employees,
                rules=effective_rules,
                history_status=HistoryStatus.KNOWN_EMPTY,
            )
        else:
            effective_context = SchedulingContext(
                base_schedule=context.base_schedule,
                previous_days=context.previous_days,
                following_days=context.following_days,
                following_schedule_id=context.following_schedule_id,
                following_schedule_version=context.following_schedule_version,
                following_max_consecutive_days=context.following_max_consecutive_days,
                history_schedule_id=context.history_schedule_id,
                history_schedule_version=context.history_schedule_version,
                employees=employees,
                rules=effective_rules,
                requested_changes=context.requested_changes,
                user_forced_assignments=context.user_forced_assignments,
                override_scopes=context.override_scopes,
                history_status=context.history_status,
                minimize_changes=context.minimize_changes,
            )

        facts = SchedulingFacts(effective_context, schedule.week_start)
        employee_by_id = {employee.id: employee for employee in employees}
        violations: dict[str, list[RuleViolation]] = {
            rule_id: [] for rule_id in HARD_RULE_IDS
        }

        valid_assignments = []
        for assignment in schedule.assignments:
            if assignment.employee_id not in employee_by_id:
                violations["R09"].append(
                    RuleViolation(
                        rule_id="R09",
                        employee_id=assignment.employee_id,
                        day=assignment.day,
                        shift=assignment.shift,
                        message="Assignment references an employee outside master data.",
                        details={"expected": "existing_employee", "actual": assignment.employee_id},
                    )
                )
            else:
                valid_assignments.append(assignment)

        by_employee_day: dict[tuple[str, Day], list[Shift]] = defaultdict(list)
        by_slot: dict[tuple[Day, Shift], set[str]] = defaultdict(set)
        assignment_keys: set[tuple[str, Day, Shift]] = set()
        duplicate_keys: set[tuple[str, Day, Shift]] = set()
        for assignment in valid_assignments:
            key = (assignment.employee_id, assignment.day, assignment.shift)
            if key in assignment_keys:
                duplicate_keys.add(key)
            assignment_keys.add(key)
            by_employee_day[(assignment.employee_id, assignment.day)].append(assignment.shift)
            by_slot[(assignment.day, assignment.shift)].add(assignment.employee_id)

        # H01 catches both double shifts and duplicate assignment records.
        for (employee_id, day), shifts in by_employee_day.items():
            if len(shifts) > 1:
                violations["H01"].append(
                    RuleViolation(
                        rule_id="H01",
                        employee_id=employee_id,
                        day=day,
                        message="Employee has more than one assignment on the same day.",
                        details={"shifts": [shift.value for shift in shifts], "maximum": 1, "actual": len(shifts)},
                    )
                )
        for employee_id, day, shift in sorted(
            duplicate_keys, key=lambda item: (item[0], WEEK_DAYS.index(item[1]), item[2].value)
        ):
            violations["H01"].append(
                RuleViolation(
                    rule_id="H01",
                    employee_id=employee_id,
                    day=day,
                    shift=shift,
                    message="Duplicate assignment record is not allowed.",
                    details={"expected": "unique_assignment", "actual": "duplicate_assignment"},
                )
            )

        coverage_specs = (
            ("R01", Skill.MANAGER, effective_rules.manager_per_shift, "manager"),
            ("R02", Skill.BEVERAGE, effective_rules.beverage_per_shift, "beverage"),
            ("R03", Skill.CASHIER, effective_rules.cashier_per_shift, "cashier"),
        )
        coverage = []
        for day in WEEK_DAYS:
            for shift in SHIFTS:
                assigned_ids = by_slot[(day, shift)]
                for rule_id, skill, required, label in coverage_specs:
                    actual = sum(
                        1 for employee_id in assigned_ids if skill in employee_by_id[employee_id].skills
                    )
                    coverage.append(dict(rule_id=rule_id, day=day, shift=shift, expected=required, actual=actual, passed=actual >= required))
                    if actual < required:
                        violations[rule_id].append(
                            RuleViolation(
                                rule_id=rule_id,
                                day=day,
                                shift=shift,
                                message=f"{label.capitalize()} coverage is below the required minimum.",
                                details={"required": required, "actual": actual},
                            )
                        )
                required_staff = effective_rules.minimum_staff(day)
                actual_staff = len(assigned_ids)
                coverage.append(dict(rule_id="R04", day=day, shift=shift, expected=required_staff, actual=actual_staff, passed=actual_staff >= required_staff))
                if actual_staff < required_staff:
                    violations["R04"].append(
                        RuleViolation(
                            rule_id="R04",
                            day=day,
                            shift=shift,
                            message="Total staffing is below the required minimum.",
                            details={"required": required_staff, "actual": actual_staff},
                        )
                    )
                # Validate request-scoped headcount bounds independently from
                # the default minimum rule. This keeps Exact and max requests
                # visible even when the baseline R04 minimum passes.
                for index, constraint in enumerate(effective_rules.staffing_for(day, shift)):
                    minimum = constraint.min_count
                    maximum = constraint.max_count
                    target = constraint.target_count
                    if minimum is not None and actual_staff < minimum:
                        violations["R04"].append(RuleViolation(
                            rule_id="R04", day=day, shift=shift,
                            message="Staffing is below the requested minimum.",
                            details={"constraint_index": index, "required": minimum, "actual": actual_staff},
                        ))
                    if maximum is not None and actual_staff > maximum:
                        violations["R04"].append(RuleViolation(
                            rule_id="R04", day=day, shift=shift,
                            message="Staffing exceeds the requested maximum.",
                            details={"constraint_index": index, "maximum": maximum, "actual": actual_staff, "excess": actual_staff - maximum},
                        ))
                    if target is not None and minimum is not None and maximum is not None and minimum == maximum == target and actual_staff != target:
                        violations["R04"].append(RuleViolation(
                            rule_id="R04", day=day, shift=shift,
                            message="Exact staffing target was not met.",
                            details={"constraint_index": index, "target": target, "actual": actual_staff, "excess": max(0, actual_staff-target), "shortage": max(0, target-actual_staff)},
                        ))
                    coverage.append(dict(rule_id="R04", day=day, shift=shift, expected=target if target is not None else (minimum if minimum is not None else maximum),
                                         target_count=target, min_count=minimum, max_count=maximum,
                                         passed=not ((minimum is not None and actual_staff < minimum) or (maximum is not None and actual_staff > maximum))))

        # R05 counts unique employee/day/shift keys; duplicates already fail H01.
        workload: dict[str, int] = defaultdict(int)
        for employee_id, _day, _shift in assignment_keys:
            workload[employee_id] += 1
        for employee_id, assigned_count in workload.items():
            if assigned_count > effective_rules.max_shifts_per_week:
                violations["R05"].append(
                    RuleViolation(
                        rule_id="R05",
                        employee_id=employee_id,
                        message="Employee exceeds the weekly shift limit.",
                        details={
                            "maximum": effective_rules.max_shifts_per_week,
                            "actual": assigned_count,
                        },
                    )
                )

        # Keep real dates/shifts in protected-rule explanations, including boundaries.
        dated_shifts: dict[tuple[str, int], set[str]] = defaultdict(set)
        for item in valid_assignments:
            dated_shifts[(item.employee_id, WEEK_DAYS.index(item.day))].add(item.shift.value)
        for items, week_offset in (
            (effective_context.previous_days, -7), (effective_context.following_days, 7),
        ):
            for item in items:
                offset = (
                    (item.assignment_date - schedule.week_start).days
                    if item.assignment_date is not None else week_offset + WEEK_DAYS.index(item.day)
                )
                dated_shifts[(item.employee_id, offset)].add(item.shift.value)

        def assignment_details(employee_id: str, start: int, end: int) -> list[dict]:
            return [
                {
                    "date": (schedule.week_start + timedelta(days=offset)).isoformat(),
                    "shifts": sorted(dated_shifts[(employee_id, offset)]),
                }
                for offset in range(start, end)
            ]

        # R06 checks only windows that intersect the current week.
        for employee_id in employee_by_id:
            previous = facts.previous_work_vector(employee_id)
            current = [int((employee_id, day) in by_employee_day) for day in WEEK_DAYS]
            timeline = previous + current + facts.following_work_vector(employee_id)
            for start, end, maximum in facts.r06_windows(len(previous), len(timeline)):
                if sum(timeline[start:end]) > maximum:
                    first_current = max(0, start - len(previous))
                    last_current = min(len(WEEK_DAYS) - 1, end - len(previous) - 1)
                    assignments = assignment_details(
                        employee_id, start - len(previous), end - len(previous)
                    )
                    shift_names = {"morning": "早班", "evening": "晚班"}
                    assignment_text = "、".join(
                        item["date"] + "/".join(shift_names[shift] for shift in item["shifts"])
                        for item in assignments
                    )
                    violations["R06"].append(
                        RuleViolation(
                            rule_id="R06",
                            employee_id=employee_id,
                            day=WEEK_DAYS[last_current],
                            message=(
                                f"员工 {employee_id} 在 {assignments[0]['date']} 至 "
                                f"{assignments[-1]['date']} 连续工作 {end - start} 天，"
                                f"违反 R06（最多 {maximum} 天）。"
                                f"具体班次：{assignment_text}。"
                            ),
                            details={
                                "maximum": maximum,
                                "actual": sum(timeline[start:end]),
                                "assignments": assignments,
                                "current_week_window": [
                                    day.value for day in WEEK_DAYS[first_current : last_current + 1]
                                ],
                            },
                        )
                    )

        def add_r07(employee_id: str, evening_offset: int) -> None:
            assignments = assignment_details(employee_id, evening_offset, evening_offset + 2)
            current_index = max(0, min(evening_offset + 1, len(WEEK_DAYS) - 1))
            violations["R07"].append(RuleViolation(
                rule_id="R07",
                employee_id=employee_id,
                day=WEEK_DAYS[current_index],
                shift=Shift.EVENING if evening_offset == 6 else Shift.MORNING,
                message=(
                    f"员工 {employee_id} 在 {assignments[0]['date']} 晚班后接 "
                    f"{assignments[1]['date']} 早班，违反 R07（晚班后不能接次日早班）。"
                ),
                details={
                    "previous_day": WEEK_DAYS[evening_offset].value,
                    "expected": "rest_after_evening", "actual": "morning_after_evening",
                    "assignments": assignments,
                },
            ))

        # R07 checks both confirmed boundaries and all adjacent current days.
        for employee_id in employee_by_id:
            if facts.previous_sunday_evening(employee_id) and (
                employee_id,
                Day.MON,
                Shift.MORNING,
            ) in assignment_keys:
                add_r07(employee_id, -1)
            if facts.following_monday_morning(employee_id) and (
                employee_id, Day.SUN, Shift.EVENING,
            ) in assignment_keys:
                add_r07(employee_id, 6)
            for day_index in range(len(WEEK_DAYS) - 1):
                current_day = WEEK_DAYS[day_index]
                next_day = WEEK_DAYS[day_index + 1]
                if (
                    employee_id,
                    current_day,
                    Shift.EVENING,
                ) in assignment_keys and (
                    employee_id,
                    next_day,
                    Shift.MORNING,
                ) in assignment_keys:
                    add_r07(employee_id, day_index)

        # R08 uses the effective one-run policy, including requested temporary leave.
        for assignment in valid_assignments:
            if not facts.employee_can_work(
                assignment.employee_id, assignment.day, assignment.shift
            ):
                violations["R08"].append(
                    RuleViolation(
                        rule_id="R08",
                        employee_id=assignment.employee_id,
                        day=assignment.day,
                        shift=assignment.shift,
                        message="Employee is on leave or unavailable for this shift.",
                    )
                )

        checks = {
            rule_id: RuleCheck(passed=not rule_violations, violations=rule_violations)
            for rule_id, rule_violations in violations.items()
        }
        flattened = [
            violation
            for rule_id in HARD_RULE_IDS
            for violation in violations[rule_id]
        ]
        passed_count = sum(check.passed for check in checks.values())
        return ValidationResult(
            coverage=coverage,
            valid=not flattened,
            hard_constraints=checks,
            violations=flattened,
            passed_count=passed_count,
        )


def validate_schedule(
    schedule: Schedule,
    employees: list[Employee],
    context: SchedulingContext | None = None,
    rules: RuleConfig | None = None,
) -> ValidationResult:
    return RuleValidator().validate(schedule, employees, context, rules)
