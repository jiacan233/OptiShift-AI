from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.core import HistoryUnavailableError, SchedulingFacts
from backend.app.models import (
    Assignment,
    Day,
    HistoricalAssignment,
    HistoryStatus,
    Schedule,
    SchedulingContext,
    Shift,
)
from backend.app.services.context_builder import ContextBuilder


def _confirm(schedules, schedule: Schedule, *, lineage_id: str | None = None) -> None:
    schedules.save_draft(
        schedule,
        lineage_id=lineage_id or schedule.schedule_id,
        base_schedule_id=None,
        base_version=None,
        validation={"passed": True},
    )
    schedules.confirm(schedule.schedule_id, schedule.version)


def test_previous_work_vector_uses_exact_dates(employee_factory, week_start):
    employee = employee_factory("E01")
    history = [
        HistoricalAssignment(
            employee_id="E01",
            day=Day.WED,
            shift=Shift.MORNING,
            assignment_date=week_start - timedelta(days=5),
        ),
        HistoricalAssignment(
            employee_id="E01",
            day=Day.SUN,
            shift=Shift.EVENING,
            assignment_date=week_start - timedelta(days=1),
        ),
    ]
    context = SchedulingContext(
        employees=[employee], previous_days=history, history_status=HistoryStatus.AVAILABLE
    )

    facts = SchedulingFacts(context, week_start)
    assert facts.previous_work_vector("E01") == [1, 0, 0, 0, 1]
    assert facts.previous_sunday_evening("E01") == 1


def test_previous_work_vector_falls_back_to_weekdays(employee_factory):
    employee = employee_factory("E01")
    context = SchedulingContext(
        employees=[employee],
        previous_days=[
            HistoricalAssignment(employee_id="E01", day=Day.FRI, shift=Shift.MORNING),
            HistoricalAssignment(employee_id="E01", day=Day.SUN, shift=Shift.EVENING),
        ],
        history_status=HistoryStatus.AVAILABLE,
    )

    facts = SchedulingFacts(context)
    assert facts.previous_work_vector("E01") == [0, 0, 1, 0, 1]
    assert facts.previous_sunday_evening("E01") == 1


def test_history_unavailable_is_not_treated_as_empty(employee_factory):
    context = SchedulingContext(
        employees=[employee_factory("E01")], history_status=HistoryStatus.UNAVAILABLE
    )

    with pytest.raises(HistoryUnavailableError):
        SchedulingFacts(context)


def test_context_builder_marks_first_week_known_empty(repositories, week_start):
    employees, schedules = repositories
    builder = ContextBuilder(employees, schedules)

    context = builder.build(week_start)

    assert context.history_status is HistoryStatus.KNOWN_EMPTY
    assert context.previous_days == []


def test_context_builder_loads_exact_previous_confirmed_week(
    repositories, employee_factory, week_start
):
    employees, schedules = repositories
    employees.create(employee_factory("E01"))
    previous_week = week_start - timedelta(days=7)
    previous = Schedule(
        schedule_id="previous",
        week_start=previous_week,
        assignments=[Assignment(employee_id="E01", day=Day.SUN, shift=Shift.EVENING)],
    )
    _confirm(schedules, previous)

    context = ContextBuilder(employees, schedules).build(week_start)

    assert context.history_status is HistoryStatus.AVAILABLE
    assert len(context.previous_days) == 1
    assert context.previous_days[0].assignment_date == week_start - timedelta(days=1)


def test_context_builder_marks_gap_as_history_unavailable(
    repositories, employee_factory, week_start
):
    employees, schedules = repositories
    employees.create(employee_factory("E01"))
    older = Schedule(
        schedule_id="older",
        week_start=week_start - timedelta(days=14),
        assignments=[],
    )
    _confirm(schedules, older)

    context = ContextBuilder(employees, schedules).build(week_start)

    assert context.history_status is HistoryStatus.UNAVAILABLE
    assert context.previous_days == []

