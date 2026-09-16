from __future__ import annotations

import pytest

from backend.app.models import ChangeType, Day, ScheduleChange
from backend.app.repository import VersionConflictError


def _generate_and_confirm(service, week_start):
    generated = service.generate(week_start=week_start)
    assert generated["status"] == "feasible"
    assert generated["validation"]["passed"]
    confirmed = service.confirm(generated["schedule_id"], generated["version"])
    return generated, confirmed


def _leave(employee_id="E02", day=Day.FRI):
    return ScheduleChange(employee_id=employee_id, type=ChangeType.LEAVE, day=day)


def test_temporary_leave_produces_necessary_changes_only(demo_service, week_start):
    _, confirmed = _generate_and_confirm(demo_service, week_start)

    draft = demo_service.replan(
        base_schedule_id=confirmed["schedule_id"],
        base_version=confirmed["version"],
        changes=[_leave()],
        minimize_changes=True,
    )

    assert draft["status"] == "feasible"
    assert draft["validation"]["passed"]
    assert not any(
        item["employee_id"] == "E02" and item["day"] == "Fri"
        for item in draft["schedule"]["assignments"]
    )
    changed = len(draft["diff"]["added"]) + len(draft["diff"]["removed"])
    assert draft["metrics"]["changed_assignments"] == changed
    assert draft["diff"]["hard_violations"] == 0
    assert draft["diff"]["unchanged_shifts"] >= 12


def test_confirmed_schedule_not_overwritten_by_draft(demo_service, week_start):
    _, confirmed = _generate_and_confirm(demo_service, week_start)

    draft = demo_service.replan(
        base_schedule_id=confirmed["schedule_id"],
        base_version=1,
        changes=[_leave()],
    )

    base = demo_service.schedules.get_record(confirmed["schedule_id"])
    current = demo_service.schedules.latest(status="confirmed")
    assert draft["schedule_status"] == "draft"
    assert base["status"] == "confirmed"
    assert current.schedule_id == confirmed["schedule_id"]
    assert demo_service.schedules.get_record(draft["schedule_id"])["status"] == "draft"


def test_confirm_creates_new_confirmed_version(demo_service, week_start):
    _, confirmed_v1 = _generate_and_confirm(demo_service, week_start)
    draft_v2 = demo_service.replan(
        base_schedule_id=confirmed_v1["schedule_id"],
        base_version=1,
        changes=[_leave()],
    )

    confirmed_v2 = demo_service.confirm(draft_v2["schedule_id"], 2)
    versions = demo_service.schedules.versions(confirmed_v2["schedule_id"])

    assert confirmed_v2["status"] == "confirmed"
    assert confirmed_v2["version"] == 2
    assert confirmed_v2["schedule"]["parent_schedule_id"] == confirmed_v1["schedule_id"]
    assert [(item["version"], item["status"]) for item in versions] == [
        (2, "confirmed"),
        (1, "confirmed"),
    ]


def test_cancel_preserves_confirmed_schedule(demo_service, week_start):
    _, confirmed = _generate_and_confirm(demo_service, week_start)
    draft = demo_service.replan(
        base_schedule_id=confirmed["schedule_id"],
        base_version=1,
        changes=[_leave()],
    )

    cancelled = demo_service.cancel(draft["schedule_id"], 2)

    assert cancelled["status"] == "cancelled"
    assert cancelled["confirmed_schedule"]["schedule_id"] == confirmed["schedule_id"]
    assert demo_service.schedules.latest(status="confirmed").schedule_id == confirmed["schedule_id"]


def test_two_consecutive_replans_use_correct_base(demo_service, week_start):
    _, confirmed_v1 = _generate_and_confirm(demo_service, week_start)
    draft_v2 = demo_service.replan(
        base_schedule_id=confirmed_v1["schedule_id"],
        base_version=1,
        changes=[_leave()],
    )
    confirmed_v2 = demo_service.confirm(draft_v2["schedule_id"], 2)

    draft_v3 = demo_service.replan(
        base_schedule_id=confirmed_v2["schedule_id"],
        base_version=2,
        changes=[_leave("E03", Day.TUE)],
    )

    assert draft_v3["status"] == "feasible"
    assert draft_v3["version"] == 3
    assert draft_v3["schedule"]["parent_schedule_id"] == confirmed_v2["schedule_id"]


def test_version_conflict_is_rejected(demo_service, week_start):
    _, confirmed_v1 = _generate_and_confirm(demo_service, week_start)
    draft_v2 = demo_service.replan(
        base_schedule_id=confirmed_v1["schedule_id"],
        base_version=1,
        changes=[_leave()],
    )
    demo_service.confirm(draft_v2["schedule_id"], 2)

    with pytest.raises(VersionConflictError) as error:
        demo_service.replan(
            base_schedule_id=confirmed_v1["schedule_id"],
            base_version=1,
            changes=[_leave("E03", Day.TUE)],
        )

    assert error.value.current_version == 2
    assert error.value.base_version == 1

