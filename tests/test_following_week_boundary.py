"""Generation must respect fixed confirmed assignments on both sides of a week."""

from datetime import timedelta

import pytest

from backend.app.core import SchedulingFacts
from backend.app.models import (
    WEEK_DAYS,
    Assignment,
    ChangeType,
    Day,
    DiagnosticConflict,
    ForceRequest,
    HistoricalAssignment,
    OverrideScope,
    RuleConfig,
    Schedule,
    ScheduleChange,
    SchedulingContext,
    Shift,
)
from backend.app.services.scheduling_service import SchedulingService
from backend.app.repository import VersionConflictError
from backend.app.models.orm import ScheduleRecord
from backend.app.solver import candidate_blocking_analysis
from backend.app.validator import RuleValidator


def _assignments(days, shift=Shift.MORNING):
    return [Assignment(employee_id="E01", day=day, shift=shift) for day in days]


def _setup_service(repositories, employee_factory, week_start, following_assignments,
                   *, current_maximum=5, following_maximum=None):
    employees, schedules = repositories
    employees.create(employee_factory("E01", preferred_shift=Shift.MORNING))
    service = SchedulingService(employees, schedules)
    service.context_builder.rules = RuleConfig(
        manager_per_shift=0, beverage_per_shift=0, cashier_per_shift=0,
        weekday_min_staff=0, weekend_min_staff=0,
        max_consecutive_days=current_maximum,
    )
    service.context_builder.build(week_start)  # Persist the known-empty history boundary.
    for identity, week, assignments in (
        ("base", week_start, []),
        ("following", week_start + timedelta(days=7), following_assignments),
    ):
        schedules.save_draft(
            Schedule(schedule_id=identity, week_start=week, assignments=assignments),
            lineage_id=identity, base_schedule_id=None, base_version=None,
            validation={"passed": True},
            metadata={"rule_config": service.context_builder.rules.model_copy(update={
                "max_consecutive_days": following_maximum or current_maximum,
            }).model_dump(mode="json") if identity == "following" else
                service.context_builder.rules.model_dump(mode="json")},
        )
        service.confirm(identity, 1)
    return service


@pytest.mark.parametrize("dated", [False, True])
def test_following_facts_use_exact_dates_or_weekday_fallback(
    employee_factory, week_start, dated,
):
    context = SchedulingContext(
        employees=[employee_factory("E01")],
        following_days=[
            HistoricalAssignment(
                employee_id="E01", day=day, shift=Shift.MORNING,
                assignment_date=week_start + timedelta(days=offset) if dated else None,
            )
            for day, offset in [(Day.MON, 7), (Day.FRI, 11), (Day.WED, 16)]
        ],
    )
    facts = SchedulingFacts(context, week_start)
    assert facts.following_work_vector("E01") == ([1, 0, 0, 0, 1] if dated else [1, 0, 1, 0, 1])
    assert facts.following_monday_morning("E01") == 1
    assert facts.following_work_vector("absent") == [0] * 5


def test_context_loads_confirmed_following_week_only(repositories, employee_factory, week_start):
    service = _setup_service(repositories, employee_factory, week_start, _assignments([Day.MON]))
    following_week = week_start + timedelta(days=7)
    service.schedules.save_draft(
        Schedule(schedule_id="pending", week_start=following_week, version=2,
                 parent_schedule_id="following",
                 assignments=_assignments([Day.TUE], Shift.EVENING)),
        lineage_id="following", base_schedule_id="following", base_version=1,
        validation={"passed": True},
    )
    context = service.context_builder.build(week_start)
    assert len(context.following_days) == 1
    assert context.following_days[0].assignment_date == following_week
    assert context.following_days[0].shift is Shift.MORNING
    # This week's confirmed schedule must not be mistaken for a later boundary.
    assert service.context_builder.build(following_week).following_days == []


@pytest.mark.parametrize("rule", ["R06", "R07"])
def test_normal_generation_avoids_following_conflict_and_confirms(
    repositories, employee_factory, week_start, rule,
):
    following = _assignments([Day.MON, Day.TUE] if rule == "R06" else [Day.MON])
    service = _setup_service(repositories, employee_factory, week_start, following)
    changes = [
        ScheduleChange(employee_id="E01", type=ChangeType.LEAVE, day=day)
        for day in (WEEK_DAYS[:3] if rule == "R06" else WEEK_DAYS[:5])
    ]
    if rule == "R07":
        changes += [
            ScheduleChange(employee_id="E01", type=ChangeType.PREFERENCE,
                           day=day, shift=Shift.EVENING)
            for day in (Day.SAT, Day.SUN)
        ]
        changes.append(ScheduleChange(employee_id="E01", type=ChangeType.ASSIGN,
                                      day=Day.SAT, shift=Shift.EVENING))
    before = service.schedules.confirmed_for_week(week_start + timedelta(days=7))

    result = service.generate(week_start=week_start, changes=changes)

    assert result["status"] == "feasible"
    schedule = service.schedules.get(result["schedule_id"])
    assert schedule.assignments
    assert not any(item.day is Day.SUN for item in schedule.assignments)
    assert service.validate_stored(schedule.schedule_id)["confirmable"]
    confirmed = service.confirm(schedule.schedule_id, schedule.version)
    assert confirmed["schedule_status"] == "confirmed"
    assert service.schedules.confirmed_for_week(before.week_start) == before


CONFLICTS = [
    pytest.param("R06", _assignments(WEEK_DAYS[-tail:]), _assignments(WEEK_DAYS[:6-tail]),
                 id=f"R06-{tail}-plus-{6-tail}")
    for tail in range(1, 6)
] + [
    pytest.param("R07", _assignments([Day.SUN], Shift.EVENING), _assignments([Day.MON]), id="R07"),
]


@pytest.mark.parametrize("rule,required,following", CONFLICTS)
@pytest.mark.parametrize("mode", ["normal", "force", "force_with_override"])
def test_impossible_requests_report_protected_conflict_without_draft(
    repositories, employee_factory, week_start, rule, required, following, mode,
):
    service = _setup_service(repositories, employee_factory, week_start, following)
    before = service.schedules.versions_for_week(week_start)
    context = service.context_builder.build(week_start)
    invalid = Schedule(week_start=week_start, assignments=required)
    validation = RuleValidator().validate(invalid, context.employees, context=context)
    assert rule in {item.rule_id for item in validation.violations}

    if mode == "normal":
        result = service.generate(week_start=week_start, changes=[
            ScheduleChange(**item.model_dump(), type=ChangeType.ASSIGN) for item in required
        ])
    else:
        result = service.force_generate(week_start=week_start, force_request=ForceRequest(
            authorization_reason="Attempt to force the requested assignments",
            forced_assignments=required,
            requested_overrides=[
                OverrideScope(rule_id="R04", day=Day.SUN, shift=Shift.MORNING, allowed_shortage=1),
            ] if mode == "force_with_override" else [],
        ))

    assert result["status"] == "infeasible"
    assert result["can_confirm"] is False
    assert result.get("schedule") is None
    assert result.get("preview_schedule") is None
    conflict = next(item for item in result["conflicts"] if item["rule_id"] == rule)
    assert conflict["employee_id"] == "E01"
    expected = [
        {"date": (week_start + timedelta(days=offset + WEEK_DAYS.index(item.day))).isoformat(),
         "shifts": [item.shift.value]}
        for assignments, offset in ((required, 0), (following, 7)) for item in assignments
    ]
    assert conflict["details"]["assignments"] == expected
    assert all(value in result["message"] for value in (
        "E01", rule, expected[0]["date"], expected[-1]["date"],
    ))
    assert service.schedules.current_draft_record_for_week(week_start) is None
    assert service.schedules.versions_for_week(week_start) == before


@pytest.mark.parametrize("rule", ["R06", "R07"])
def test_diagnostic_candidates_respect_following_boundary(employee_factory, week_start, rule):
    context = SchedulingContext(
        employees=[employee_factory("E01")],
        following_days=[
            HistoricalAssignment(**item.model_dump(), assignment_date=week_start + timedelta(
                days=7 + WEEK_DAYS.index(item.day),
            ))
            for item in _assignments(WEEK_DAYS[:5] if rule == "R06" else [Day.MON])
        ],
    )
    conflict = DiagnosticConflict(rule_id="R04", day=Day.SUN, shift=Shift.EVENING,
                                  required=1, actual=0, shortage=1)
    blocked = candidate_blocking_analysis(context, [conflict], week_start=week_start)
    assert rule in {reason.rule_id for reason in blocked[0].reasons}


def _advance_following(service, week_start):
    # Preserve assignments to isolate dependency freshness from rule validity.
    record = service.schedules.current_confirmed_record_for_week(week_start + timedelta(days=7))
    draft = record["schedule"].model_copy(update={
        "schedule_id": "following-v2", "version": 2, "parent_schedule_id": "following",
    })
    service.schedules.save_draft(
        draft, lineage_id="following", base_schedule_id="following", base_version=1,
        validation={"passed": True}, metadata=record["metadata"],
    )
    return service.confirm(draft.schedule_id, draft.version)


@pytest.mark.parametrize("change", ["version", "removed", "added"])
def test_following_dependency_changes_make_otherwise_valid_draft_stale(
    repositories, employee_factory, week_start, change,
):
    service = _setup_service(repositories, employee_factory, week_start, [])
    if change == "added":
        with service.schedules.database.transaction(immediate=True) as session:
            session.get(ScheduleRecord, "following").status = "cancelled"
    draft = service.generate(week_start=week_start)
    metadata = service.schedules.get_record(draft["schedule_id"])["metadata"]
    assert metadata["following_schedule_id"] == (None if change == "added" else "following")
    assert metadata["following_schedule_version"] == (None if change == "added" else 1)
    if change == "version":
        _advance_following(service, week_start)
    else:
        with service.schedules.database.transaction(immediate=True) as session:
            session.get(ScheduleRecord, "following").status = (
                "confirmed" if change == "added" else "cancelled"
            )

    for validation in (
        service.validate_stored(draft["schedule_id"]),
        service.schedules.current_records_for_week(week_start)[1]["validation"],
    ):
        assert validation["passed"] is True
        assert validation["passed_count"] == 10
        assert validation["freshness_valid"] is False
        assert validation["freshness_reason"] == "following_dependency_stale"
        assert validation["confirmable"] is False
        assert validation["conflict"]["code"] == "following_dependency_conflict"
    for confirm in (service.confirm, service.schedules.confirm):
        with pytest.raises(VersionConflictError) as error:
            confirm(draft["schedule_id"], draft["version"])
        assert error.value.code == "following_dependency_conflict"
    assert service.schedules.confirmed_for_week(week_start).schedule_id == "base"


def test_following_change_during_generation_rejects_save(repositories, employee_factory, week_start):
    service = _setup_service(repositories, employee_factory, week_start, [])
    with pytest.raises(VersionConflictError) as error:
        service.generate(week_start=week_start, before_commit=lambda: _advance_following(service, week_start))
    assert error.value.code == "following_dependency_conflict"
    assert service.schedules.current_draft_record_for_week(week_start) is None


@pytest.mark.parametrize("current_maximum,following_maximum,tail,prefix,feasible", [
    (5, 3, 2, 2, False),  # A stricter successor owns the crossing window.
    (3, 5, 3, 2, True),   # Do not apply this week's stricter limit to next week.
    (3, 5, 4, 1, False),  # This week's internal limit still applies.
    (5, 2, 1, 1, True),
])
def test_generation_and_confirm_use_the_same_r06_boundary_limit(
    repositories, employee_factory, week_start, current_maximum, following_maximum,
    tail, prefix, feasible,
):
    service = _setup_service(
        repositories, employee_factory, week_start, _assignments(WEEK_DAYS[:prefix]),
        current_maximum=current_maximum, following_maximum=following_maximum,
    )
    context = service.context_builder.build(week_start)
    assert context.rules.max_consecutive_days == current_maximum
    assert context.following_max_consecutive_days == following_maximum
    required = _assignments(WEEK_DAYS[-tail:])
    changes = [ScheduleChange(**item.model_dump(), type=ChangeType.ASSIGN) for item in required]
    result = service.generate(week_start=week_start, changes=changes)
    if feasible:
        assert result["status"] == "feasible"
        assert service.confirm(result["schedule_id"], result["version"])["status"] == "confirmed"
    else:
        assert result["status"] == "infeasible"
        violation = next(item for item in result["conflicts"] if item["rule_id"] == "R06")
        expected_limit = current_maximum if tail > current_maximum else following_maximum
        assert violation["details"]["maximum"] == expected_limit
        assert service.schedules.current_draft_record_for_week(week_start) is None
