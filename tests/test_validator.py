from __future__ import annotations

from datetime import timedelta

from backend.app.models import (
    Assignment,
    ChangeType,
    Day,
    HistoricalAssignment,
    HistoryStatus,
    RuleConfig,
    Schedule,
    ScheduleChange,
    SchedulingContext,
    Shift,
    Skill,
    WEEK_DAYS,
)
from backend.app.validator import RuleValidator


def _rules(**overrides) -> RuleConfig:
    values = {
        "manager_per_shift": 1,
        "beverage_per_shift": 1,
        "cashier_per_shift": 1,
        "weekday_min_staff": 1,
        "weekend_min_staff": 1,
        "max_shifts_per_week": 7,
        "max_consecutive_days": 7,
    }
    values.update(overrides)
    return RuleConfig(**values)


def _baseline(employee_factory, week_start, *, employees=None) -> tuple[list, Schedule]:
    employee_list = employees or [employee_factory("E01"), employee_factory("E02")]
    schedule = Schedule(
        schedule_id="validator-schedule",
        week_start=week_start,
        assignments=[
            *[
                Assignment(employee_id="E01", day=day, shift=Shift.MORNING)
                for day in WEEK_DAYS
            ],
            *[
                Assignment(employee_id="E02", day=day, shift=Shift.EVENING)
                for day in WEEK_DAYS
            ],
        ],
    )
    return employee_list, schedule


def _validate(schedule, employees, rules=None, context=None):
    effective_rules = rules if rules is not None else (context.rules if context is not None else _rules())
    return RuleValidator().validate(
        schedule, employees, context=context, rules=effective_rules
    )


def _violations(result, rule_id):
    return result.hard_constraints[rule_id].violations


def test_valid_schedule_passes_all_ten_rules(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)

    result = _validate(schedule, employees)

    assert result.valid
    assert result.passed_count == result.total_count == 10
    assert set(result.hard_constraints) == {
        "H01", "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09"
    }


def test_validator_rejects_double_shift(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)
    schedule.assignments.append(
        Assignment(employee_id="E01", day=Day.MON, shift=Shift.EVENING)
    )

    result = _validate(schedule, employees)

    assert not result.valid
    assert _violations(result, "H01")


def test_validator_rejects_duplicate_assignment(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)
    schedule.assignments.append(schedule.assignments[0].model_copy())

    result = _validate(schedule, employees)

    assert any("Duplicate" in item.message for item in _violations(result, "H01"))


def test_validator_rejects_missing_manager(employee_factory, week_start):
    employees = [
        employee_factory("E01", skills=[Skill.BEVERAGE, Skill.CASHIER]),
        employee_factory("E02"),
    ]
    employees, schedule = _baseline(employee_factory, week_start, employees=employees)

    result = _validate(schedule, employees)

    assert any(item.day is Day.MON and item.shift is Shift.MORNING for item in _violations(result, "R01"))


def test_validator_rejects_missing_beverage(employee_factory, week_start):
    employees = [
        employee_factory("E01", skills=[Skill.MANAGER, Skill.CASHIER]),
        employee_factory("E02"),
    ]
    employees, schedule = _baseline(employee_factory, week_start, employees=employees)

    result = _validate(schedule, employees)

    assert _violations(result, "R02")


def test_validator_rejects_missing_cashier(employee_factory, week_start):
    employees = [
        employee_factory("E01", skills=[Skill.MANAGER, Skill.BEVERAGE]),
        employee_factory("E02"),
    ]
    employees, schedule = _baseline(employee_factory, week_start, employees=employees)

    result = _validate(schedule, employees)

    assert _violations(result, "R03")


def test_validator_rejects_minimum_staffing_shortage(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)

    result = _validate(
        schedule,
        employees,
        rules=_rules(weekday_min_staff=2, weekend_min_staff=2),
    )

    assert len(_violations(result, "R04")) == 14


def test_validator_rejects_weekly_limit(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)

    result = _validate(schedule, employees, rules=_rules(max_shifts_per_week=5))

    assert {item.employee_id for item in _violations(result, "R05")} == {"E01", "E02"}


def test_validator_rejects_six_consecutive_days(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)

    result = _validate(schedule, employees, rules=_rules(max_consecutive_days=5))

    assert _violations(result, "R06")


def test_validator_rejects_cross_week_six_consecutive_days(
    employee_factory, week_start
):
    employees, schedule = _baseline(employee_factory, week_start)
    history = [
        HistoricalAssignment(
            employee_id="E01",
            day=Day.SUN,
            shift=Shift.MORNING,
            assignment_date=week_start - timedelta(days=1),
        )
    ]
    context = SchedulingContext(
        employees=employees,
        rules=_rules(max_consecutive_days=5),
        previous_days=history,
        history_status=HistoryStatus.AVAILABLE,
    )

    result = _validate(schedule, employees, context=context)

    assert any(
        item.employee_id == "E01" and item.day is Day.FRI
        for item in _violations(result, "R06")
    )


def test_validator_rejects_evening_to_morning(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)
    schedule.assignments.append(
        Assignment(employee_id="E02", day=Day.TUE, shift=Shift.MORNING)
    )

    result = _validate(schedule, employees)

    assert any(
        item.employee_id == "E02" and item.day is Day.TUE
        for item in _violations(result, "R07")
    )


def test_validator_rejects_cross_week_evening_to_morning(
    employee_factory, week_start
):
    employees, schedule = _baseline(employee_factory, week_start)
    context = SchedulingContext(
        employees=employees,
        rules=_rules(),
        previous_days=[
            HistoricalAssignment(
                employee_id="E01",
                day=Day.SUN,
                shift=Shift.EVENING,
                assignment_date=week_start - timedelta(days=1),
            )
        ],
        history_status=HistoryStatus.AVAILABLE,
    )

    result = _validate(schedule, employees, context=context)

    assert any(
        item.employee_id == "E01" and item.day is Day.MON
        for item in _violations(result, "R07")
    )


def test_validator_rejects_leave_assignment(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)
    context = SchedulingContext(
        employees=employees,
        rules=_rules(),
        requested_changes=[
            ScheduleChange(employee_id="E01", type=ChangeType.LEAVE, day=Day.MON)
        ],
    )

    result = _validate(schedule, employees, context=context)

    assert any(item.employee_id == "E01" and item.day is Day.MON for item in _violations(result, "R08"))


def test_validator_rejects_unavailable_assignment(employee_factory, week_start):
    employees = [
        employee_factory("E01", available_days=list(WEEK_DAYS[1:])),
        employee_factory("E02"),
    ]
    employees, schedule = _baseline(employee_factory, week_start, employees=employees)

    result = _validate(schedule, employees)

    assert any(item.employee_id == "E01" and item.day is Day.MON for item in _violations(result, "R08"))


def test_validator_rejects_employee_outside_master_data(employee_factory, week_start):
    employees, schedule = _baseline(employee_factory, week_start)
    schedule.assignments.append(
        Assignment(employee_id="E999", day=Day.MON, shift=Shift.MORNING)
    )

    result = _validate(schedule, employees)

    assert any(item.employee_id == "E999" for item in _violations(result, "R09"))


def test_validator_never_infers_skill_from_role(employee_factory, week_start):
    employees = [
        employee_factory(
            "E01",
            role="manager",
            skills=[Skill.BEVERAGE, Skill.CASHIER],
        ),
        employee_factory("E02"),
    ]
    employees, schedule = _baseline(employee_factory, week_start, employees=employees)

    result = _validate(schedule, employees)

    assert _violations(result, "R01")
