from __future__ import annotations

import pytest

from backend.app.models import Assignment, Day, Schedule, Shift
from backend.app.repository import (
    DraftPendingError,
    DraftNotFoundError,
    InvalidScheduleStateError,
    VersionConflictError,
)


def _schedule(schedule_id, week_start, version=1, parent=None):
    return Schedule(
        schedule_id=schedule_id,
        version=version,
        parent_schedule_id=parent,
        week_start=week_start,
        assignments=[Assignment(employee_id="E01", day=Day.MON, shift=Shift.MORNING)],
    )


def _save(repository, schedule, *, lineage, base=None, base_version=None, passed=True):
    repository.save_draft(
        schedule,
        lineage_id=lineage,
        base_schedule_id=base,
        base_version=base_version,
        validation={"passed": passed},
        metadata={"marker": schedule.schedule_id},
    )


def test_draft_confirm_and_version_lineage(repositories, week_start):
    _, repository = repositories
    v1 = _schedule("v1", week_start)
    _save(repository, v1, lineage="lineage")
    repository.confirm("v1", 1)
    v2 = _schedule("v2", week_start, version=2, parent="v1")
    _save(repository, v2, lineage="lineage", base="v1", base_version=1)

    before = repository.versions("v1")
    confirmed = repository.confirm("v2", 2)
    after = repository.versions("v2")

    assert before[0]["status"] == "draft"
    assert confirmed.version == 2
    assert confirmed.status.value == "confirmed"
    assert [(item["version"], item["status"]) for item in after] == [
        (2, "confirmed"),
        (1, "confirmed"),
    ]
    assert repository.latest(status="confirmed").schedule_id == "v2"


def test_confirm_rejects_invalid_draft(repositories, week_start):
    _, repository = repositories
    schedule = _schedule("invalid", week_start)
    _save(repository, schedule, lineage="invalid", passed=False)

    with pytest.raises(InvalidScheduleStateError):
        repository.confirm("invalid", 1)


def test_confirm_rejects_wrong_version(repositories, week_start):
    _, repository = repositories
    schedule = _schedule("draft", week_start)
    _save(repository, schedule, lineage="draft")

    with pytest.raises(VersionConflictError) as error:
        repository.confirm("draft", 2)

    assert error.value.current_version == 1
    assert error.value.base_version == 2


def test_stale_base_is_rejected_after_new_version_confirmed(repositories, week_start):
    _, repository = repositories
    v1 = _schedule("v1", week_start)
    _save(repository, v1, lineage="lineage")
    repository.confirm("v1", 1)
    v2 = _schedule("v2", week_start, version=2, parent="v1")
    _save(repository, v2, lineage="lineage", base="v1", base_version=1)
    repository.confirm("v2", 2)

    with pytest.raises(VersionConflictError) as error:
        repository.assert_current_base("v1", 1)

    assert error.value.current_version == 2
    assert repository.assert_current_base("v2", 2)["schedule"].schedule_id == "v2"


def test_pending_draft_gate_rejects_second_candidate(repositories, week_start):
    _, repository = repositories
    v1 = _schedule("v1", week_start)
    _save(repository, v1, lineage="lineage")
    repository.confirm("v1", 1)
    first = _schedule("candidate-a", week_start, version=2, parent="v1")
    second = _schedule("candidate-b", week_start, version=2, parent="v1")
    _save(repository, first, lineage="lineage", base="v1", base_version=1)
    with pytest.raises(DraftPendingError) as error:
        _save(repository, second, lineage="lineage", base="v1", base_version=1)

    assert error.value.schedule_id == "candidate-a"
    assert error.value.version == 2


def test_cancel_hides_draft_without_changing_confirmed(repositories, week_start):
    _, repository = repositories
    v1 = _schedule("v1", week_start)
    _save(repository, v1, lineage="lineage")
    repository.confirm("v1", 1)
    draft = _schedule("draft-v2", week_start, version=2, parent="v1")
    _save(repository, draft, lineage="lineage", base="v1", base_version=1)

    cancelled = repository.cancel("draft-v2", 2)

    assert cancelled["status"] == "cancelled"
    assert repository.get("draft-v2") is None
    assert repository.latest(status="confirmed").schedule_id == "v1"
    with pytest.raises(DraftNotFoundError):
        repository.confirm("draft-v2", 2)
