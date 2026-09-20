"""Independent acceptance-path validation for final schedules."""

from __future__ import annotations

from collections import defaultdict

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

        # R06 checks every current and cross-boundary consecutive-day window.
        window_length = effective_rules.max_consecutive_days + 1
        for employee_id in employee_by_id:
            previous = facts.previous_work_vector(employee_id)
            current = [int((employee_id, day) in by_employee_day) for day in WEEK_DAYS]
            timeline = previous + current
            for start in range(0, len(timeline) - window_length + 1):
                end = start + window_length
                if end <= len(previous):
                    continue
                if sum(timeline[start:end]) > effective_rules.max_consecutive_days:
                    first_current = max(0, start - len(previous))
                    last_current = min(len(WEEK_DAYS) - 1, end - len(previous) - 1)
                    violations["R06"].append(
                        RuleViolation(
                            rule_id="R06",
                            employee_id=employee_id,
                            day=WEEK_DAYS[last_current],
                            message="Employee works too many consecutive days.",
                            details={
                                "maximum": effective_rules.max_consecutive_days,
                                "actual": sum(timeline[start:end]),
                                "current_week_window": [
                                    day.value for day in WEEK_DAYS[first_current : last_current + 1]
                                ],
                            },
                        )
                    )

        # R07 checks the historical Sunday boundary and all adjacent current days.
        for employee_id in employee_by_id:
            if facts.previous_sunday_evening(employee_id) and (
                employee_id,
                Day.MON,
                Shift.MORNING,
            ) in assignment_keys:
                violations["R07"].append(
                    RuleViolation(
                        rule_id="R07",
                        employee_id=employee_id,
                        day=Day.MON,
                        shift=Shift.MORNING,
                        message="Monday morning follows a previous Sunday evening shift.",
                        details={"expected": "rest_after_evening", "actual": "morning_after_evening"},
                    )
                )
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
                    violations["R07"].append(
                        RuleViolation(
                            rule_id="R07",
                            employee_id=employee_id,
                            day=next_day,
                            shift=Shift.MORNING,
                            message="Morning shift follows an evening shift on the prior day.",
                            details={"previous_day": current_day.value, "expected": "rest_after_evening", "actual": "morning_after_evening"},
                        )
                    )

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
