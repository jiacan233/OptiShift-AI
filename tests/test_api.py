from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    import backend.app.database as database_module
    from backend.app.api import dependencies
    from backend.app.main import app

    database_module.database.path = tmp_path / "api-test.db"
    dependencies.pending_clarifications.clear()
    with TestClient(app) as value:
        yield value
    dependencies.pending_clarifications.clear()


def _generate(client):
    response = client.post(
        "/api/schedule/generate",
        json={
            "week_start": "2026-09-21",
            "prompt": "帮我生成本周排班，尽量满足员工早晚班偏好。",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "feasible"
    assert payload["schedule_status"] == "draft"
    assert payload["validation"]["passed"] is True
    assert payload["validation"]["passed_count"] == 10
    return payload


def test_force_api_contract_and_persisted_ledger(client):
    assert client.patch("/api/employees/E01", json={"leave_days": ["Mon"]}).status_code == 200
    body = {
        "week_start": "2026-09-21", "base_schedule_id": None, "base_version": None,
        "client_message_id": "force-api-once",
        "force_request": {
            "authorization_reason": "明确授权 E01 周一早班请假例外",
            "requested_overrides": [{"rule_id": "R08", "employee_id": "E01", "day": "Mon", "shift": "morning"}],
            "forced_assignments": [{"employee_id": "E01", "day": "Mon", "shift": "morning"}],
        },
    }
    response = client.post("/api/schedule/force", json=body)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["compliance_status"] == "authorized_violations"
    assert draft["confirmable"] is True
    assert draft["validation"]["passed"] is False
    assert not draft["unauthorized_violations"]
    assert not draft["protected_violations"]
    assert not draft["integrity_violations"]
    assert client.post("/api/schedule/force", json=body).json()["schedule_id"] == draft["schedule_id"]
    confirmed = _confirm(client, draft)
    assert confirmed["compliance_status"] == "authorized_violations"
    versions = client.get(f"/api/schedules/{draft['schedule_id']}/versions").json()["versions"]
    assert versions[0]["violations"] == draft["violations"]
    assert versions[0]["authorized_violation_count"] == 1


def _confirm(client, payload):
    response = client.post(
        "/api/schedule/confirm",
        json={"schedule_id": payload["schedule_id"], "version": payload["version"]},
    )
    assert response.status_code == 200, response.text
    confirmed = response.json()
    assert confirmed["status"] == "confirmed"
    return confirmed


def _replan(client, base, employee_id="E02", day="Fri"):
    response = client.post(
        "/api/schedule/replan",
        json={
            "base_schedule_id": base["schedule_id"],
            "base_version": base["version"],
            "changes": [{"employee_id": employee_id, "type": "leave", "day": day}],
            "minimize_changes": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_employees_and_rules(client):
    health = client.get("/health")
    employees = client.get("/api/employees")
    rules = client.get("/api/rules")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "app": "optishift-ai", "database": True}
    assert employees.status_code == 200
    employee_ids = [item["id"] for item in employees.json()["employees"]]
    assert employee_ids == [f"E{index:02d}" for index in range(1, 21)]
    rule_ids = {item["rule_id"] for item in rules.json()["rules"]}
    assert rule_ids == {"H01", *{f"R{index:02d}" for index in range(1, 10)}, "S01", "S02", "S03"}


def test_employee_creation_route_is_unavailable_and_roster_stays_closed(client):
    response = client.post(
        "/api/employees",
        json={
            "id": "E21",
            "role": "clerk",
            "skills": ["beverage"],
            "available_days": ["Mon"],
            "leave_days": [],
            "preferred_shift": None,
        },
    )

    assert response.status_code in {404, 405}
    employees = client.get("/api/employees")
    assert employees.status_code == 200
    assert [item["id"] for item in employees.json()["employees"]] == [
        f"E{index:02d}" for index in range(1, 21)
    ]


def test_employee_profile_patch_remains_available(client):
    response = client.patch(
        "/api/employees/E01",
        json={
            "available_days": ["Mon", "Tue", "Fri"],
            "leave_days": ["Tue"],
            "preferred_shift": "evening",
        },
    )

    assert response.status_code == 200
    assert response.json()["available_days"] == ["Mon", "Tue", "Fri"]
    assert response.json()["leave_days"] == ["Tue"]
    assert response.json()["preferred_shift"] == "evening"


def test_generate_validate_confirm_replan_versions_and_replan_again(client):
    draft_v1 = _generate(client)
    validation = client.post(
        "/api/schedule/validate",
        json={"schedule_id": draft_v1["schedule_id"], "version": 1},
    )
    assert validation.status_code == 200
    assert validation.json()["validation"]["passed"] is True
    confirmed_v1 = _confirm(client, draft_v1)

    draft_v2 = _replan(client, confirmed_v1)
    assert draft_v2["status"] == "feasible"
    assert draft_v2["version"] == 2
    assert draft_v2["validation"]["passed"] is True
    assert not any(
        item["employee_id"] == "E02" and item["day"] == "Fri"
        for item in draft_v2["schedule"]["assignments"]
    )
    assert client.get("/api/schedules/latest?status=confirmed").json()["schedule_id"] == confirmed_v1["schedule_id"]
    confirmed_v2 = _confirm(client, draft_v2)

    versions = client.get(f"/api/schedules/{confirmed_v2['schedule_id']}/versions")
    assert versions.status_code == 200
    assert [(item["version"], item["status"]) for item in versions.json()["versions"]] == [
        (2, "confirmed"),
        (1, "confirmed"),
    ]

    draft_v3 = _replan(client, confirmed_v2, employee_id="E03", day="Tue")
    assert draft_v3["status"] == "feasible"
    assert draft_v3["version"] == 3
    assert draft_v3["schedule"]["parent_schedule_id"] == confirmed_v2["schedule_id"]


def test_api_returns_version_conflict_shape(client):
    confirmed_v1 = _confirm(client, _generate(client))
    confirmed_v2 = _confirm(client, _replan(client, confirmed_v1))

    stale = client.post(
        "/api/schedule/replan",
        json={
            "base_schedule_id": confirmed_v1["schedule_id"],
            "base_version": 1,
            "changes": [{"employee_id": "E03", "type": "leave", "day": "Tue"}],
        },
    )

    assert stale.status_code == 409
    details = stale.json()["error"]["details"]
    assert details == {
        "status": "current_week_base_conflict",
        "current_version": confirmed_v2["version"],
        "base_version": 1,
        "action": "regenerate_draft",
    }


def test_inline_invalid_schedule_is_rejected_by_validator(client):
    response = client.post(
        "/api/schedule/validate",
        json={
            "schedule": {
                "schedule_id": "manual-invalid",
                "version": 1,
                "status": "draft",
                "week_start": "2026-09-21",
                "assignments": [
                    {"employee_id": "E01", "day": "Mon", "shift": "morning"}
                ],
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "validated"
    assert payload["validation"]["passed"] is False
    assert payload["validation"]["passed_count"] < 10


def test_employee_management_allows_preferences_but_not_skills(client):
    preferred = client.patch(
        "/api/employees/E13", json={"preferred_shift": "evening"}
    )
    forbidden = client.patch(
        "/api/employees/E13", json={"skills": ["manager"]}
    )

    assert preferred.status_code == 200
    assert preferred.json()["preferred_shift"] == "evening"
    assert forbidden.status_code == 422
    current = next(
        item for item in client.get("/api/employees").json()["employees"] if item["id"] == "E13"
    )
    assert "manager" not in current["skills"]


def test_clarification_must_be_resolved_with_real_employee(client):
    response = client.post(
        "/api/schedule/generate",
        json={
            "week_start": "2026-09-21",
            "prompt": "那个兼职周日请假，其他员工尽量少调整",
        },
    )
    assert response.status_code == 200
    clarification = response.json()
    assert clarification["status"] == "clarification_required"
    candidate_ids = {
        item["employee_id"] for item in clarification["clarification"]["candidates"]
    }
    selected = sorted(candidate_ids)[0]

    resolved = client.post(
        "/api/schedule/resolve",
        json={
            "clarification_id": clarification["clarification"]["id"],
            "employee_id": selected,
        },
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "feasible"
    assert not any(
        item["employee_id"] == selected and item["day"] == "Sun"
        for item in resolved.json()["schedule"]["assignments"]
    )


def test_non_monday_and_unknown_employee_return_validation_errors(client):
    non_monday = client.post(
        "/api/schedule/generate", json={"week_start": "2026-09-22"}
    )
    unknown = client.post(
        "/api/schedule/generate",
        json={
            "week_start": "2026-09-21",
            "changes": [{"employee_id": "E999", "type": "leave", "day": "Fri"}],
        },
    )

    assert non_monday.status_code == 422
    assert non_monday.json()["error"]["code"] == "validation_error"
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "validation_error"


def test_infeasible_api_never_returns_or_persists_schedule(client):
    employees = client.get("/api/employees").json()["employees"]
    manager_ids = [item["id"] for item in employees if "manager" in item["skills"]]
    response = client.post(
        "/api/schedule/generate",
        json={
            "week_start": "2026-09-21",
            "changes": [
                {"employee_id": employee_id, "type": "leave", "day": "Sun"}
                for employee_id in manager_ids
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "infeasible"
    assert payload["generated_valid_schedule"] is False
    assert "schedule" not in payload
    assert client.get("/api/schedules/latest?status=draft").json() is None
