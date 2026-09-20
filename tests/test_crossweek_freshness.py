from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.models import ScheduleStatus
from backend.app.models.orm import ScheduleRecord
from backend.app.repository import VersionConflictError


WEEK_41 = "2026-10-05"
WEEK_42 = "2026-10-12"


@pytest.fixture
def client(tmp_path):
    from backend.app.database import database
    from backend.app.main import app
    database.path = tmp_path / "crossweek.db"
    with TestClient(app) as client:
        yield client


def generate(client, week):
    response = client.post("/api/schedule/generate", json={"week_start": week})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "feasible", response.text
    return response.json()


def operation(client, action, draft, version=None):
    return client.post(f"/api/schedule/{action}", json={
        "schedule_id": draft["schedule_id"],
        "version": draft["version"] if version is None else version,
    })


def advance(repo, base):
    """A new valid history version with unchanged assignments isolates freshness from rules."""
    record = repo.get_record(base.schedule_id)
    draft = base.model_copy(update={
        "schedule_id": f"sch_{uuid4().hex[:12]}", "version": base.version + 1,
        "parent_schedule_id": base.schedule_id, "status": ScheduleStatus.DRAFT,
    })
    repo.save_draft(draft, lineage_id=record["lineage_id"],
                    base_schedule_id=base.schedule_id, base_version=base.version,
                    validation=record["validation"], metadata=record["metadata"])
    return repo.confirm(draft.schedule_id, draft.version)


@pytest.fixture
def crossweek(client):
    from backend.app.api.dependencies import schedule_repository as repo
    first = generate(client, WEEK_41)
    assert operation(client, "confirm", first).status_code == 200
    history = repo.get(first["schedule_id"])
    for _ in range(4):
        history = advance(repo, history)
    draft = generate(client, WEEK_42)
    return repo, history, draft


def test_a_history_conflict_contract_and_repository_guard(client, crossweek):
    repo, expected, draft = crossweek
    current = advance(repo, expected)
    record = repo.get_record(draft["schedule_id"])
    assert record["base_schedule_id"] is None and record["base_version"] is None
    assert repo.confirmed_for_week(date.fromisoformat(WEEK_42)) is None
    response = operation(client, "confirm", draft)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "history_dependency_conflict"
    assert error["details"] == {
        "status": "history_dependency_conflict", "current_version": 6, "base_version": 5,
        "target_week_start": WEEK_42, "dependency_week_start": WEEK_41,
        "draft_schedule_id": draft["schedule_id"], "draft_version": 1,
        "expected_history_schedule_id": expected.schedule_id, "expected_history_version": 5,
        "current_history_schedule_id": current.schedule_id, "current_history_version": 6,
        "action": "regenerate_draft",
    }
    with pytest.raises(VersionConflictError) as caught:
        repo.confirm(draft["schedule_id"], 1)
    assert caught.value.code == "history_dependency_conflict"
    assert repo.get_record(draft["schedule_id"])["status"] == "draft"


def test_b_matching_history_confirms(client, crossweek):
    _, _, draft = crossweek
    response = operation(client, "confirm", draft)
    assert response.status_code == 200, response.text
    assert response.json()["schedule_status"] == "confirmed"


def test_c_rules_pass_but_validate_and_week_context_mark_stale(client, crossweek):
    repo, history, draft = crossweek
    advance(repo, history)
    response = operation(client, "validate", draft)
    assert response.status_code == 200
    context = client.get("/api/schedules/week-context", params={"week_start": WEEK_42}).json()
    assert context["confirmed_schedule"] is None
    for result in [response.json(), context["result"]]:
        validation = result["validation"]
        assert validation["passed"] is True
        assert validation["passed_count"] == validation["total"] == 10
        assert validation["rules_valid"] is True
        assert validation["freshness_valid"] is False
        assert validation["freshness_state"] == "stale"
        assert validation["freshness_reason"] == "history_dependency_stale"
        assert validation["confirmable"] is False
        assert result["confirmable"] is False
    assert operation(client, "cancel", draft).status_code == 200


def test_d_cancel_and_regenerate_rebinds_latest_history(client, crossweek):
    repo, history, draft = crossweek
    current = advance(repo, history)
    assert operation(client, "cancel", draft).status_code == 200
    fresh = generate(client, WEEK_42)
    assert fresh["schedule_id"] != draft["schedule_id"]
    metadata = repo.get_record(fresh["schedule_id"])["metadata"]
    assert metadata["history_schedule_id"] == current.schedule_id
    assert metadata["history_schedule_version"] == 6
    validated = operation(client, "validate", fresh).json()["validation"]
    assert validated["freshness_valid"] and validated["confirmable"]
    assert operation(client, "confirm", fresh).status_code == 200


@pytest.mark.parametrize("action", ["confirm", "cancel", "validate"])
def test_e_draft_version_takes_priority_over_stale_history(client, crossweek, action):
    repo, history, draft = crossweek
    advance(repo, history)
    response = operation(client, action, draft, version=2)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "draft_version_conflict"


def test_f_current_week_base_conflict(client, crossweek):
    repo, _, draft = crossweek
    assert operation(client, "confirm", draft).status_code == 200
    pending = generate(client, WEEK_42)
    # Simulate a competing writer/import replacing the base after draft generation.
    assert operation(client, "cancel", pending).status_code == 200
    replacement = generate(client, WEEK_42)
    assert operation(client, "confirm", replacement).status_code == 200
    with repo.database.transaction(immediate=True) as session:
        session.get(ScheduleRecord, pending["schedule_id"]).status = "draft"
    response = operation(client, "confirm", pending)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "current_week_base_conflict"
    validation = operation(client, "validate", pending).json()["validation"]
    assert validation["freshness_reason"] == "current_week_base_stale"
    assert validation["confirmable"] is False


def test_history_change_during_validation_is_still_a_conflict(client, crossweek, monkeypatch):
    from backend.app.api.dependencies import scheduling_service
    repo, history, draft = crossweek
    validate = scheduling_service.validate_stored

    def racing_validate(*args, **kwargs):
        result = validate(*args, **kwargs)
        advance(repo, history)
        return result

    monkeypatch.setattr(scheduling_service, "validate_stored", racing_validate)
    response = operation(client, "confirm", draft)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "history_dependency_conflict"
