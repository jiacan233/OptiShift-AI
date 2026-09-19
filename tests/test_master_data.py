from __future__ import annotations

from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import backend.app.database as database_module
from backend.app.database import (
    DEMO_EMPLOYEE_FIXTURE_VERSION,
    DEMO_EMPLOYEES,
    Database,
    EmployeeRecord,
    SystemMetadataRecord,
    seed_demo_employees,
)
from backend.app.main import app
from backend.app.models import (
    Day,
    Employee,
    ForceRequest,
    OverrideScope,
    RuleConfig,
    SchedulingContext,
    Shift,
    SolverStatus,
)
from backend.app.solver import PrimarySolver
from backend.app.validator import RuleValidator
from backend.app.validator.authorization import classify_validation


@pytest.fixture
def client(tmp_path):
    from backend.app.api import dependencies

    database_module.database.path = tmp_path / "master-data-test.db"
    database_module.database.initialize()
    seed_demo_employees(database_module.database)
    dependencies.pending_clarifications.clear()
    with TestClient(app) as value:
        yield value
    dependencies.pending_clarifications.clear()


def test_canonical_20_employees_master_data(client):
    response = client.get("/api/employees")
    assert response.status_code == 200
    employees = {item["id"]: item for item in response.json()["employees"]}
    assert len(employees) == 20
    assert set(employees.keys()) == {f"E{i:02d}" for i in range(1, 21)}

    # Check key employees
    e01 = employees["E01"]
    assert e01["role"] == "manager"
    assert set(e01["skills"]) == {"manager", "beverage", "cashier", "inventory"}
    assert e01["leave_days"] == ["Wed"]
    assert e01["preferred_shift"] == "morning"

    e02 = employees["E02"]
    assert e02["role"] == "vice_manager"
    assert e02["leave_days"] == []
    assert e02["preferred_shift"] == "evening"

    e06 = employees["E06"]
    assert e06["role"] == "clerk"
    assert e06["leave_days"] == ["Tue"]

    e17 = employees["E17"]
    assert e17["role"] == "clerk"
    assert e17["leave_days"] == ["Mon"]

    e20 = employees["E20"]
    assert e20["role"] == "clerk"
    assert e20["leave_days"] == ["Thu"]
    assert e20["preferred_shift"] == "morning"


def test_versioned_demo_sync_idempotence_and_upgrade(tmp_path):
    from backend.app.database import utc_now

    db_path = tmp_path / "upgrade-test.db"
    db = Database(db_path)
    db.initialize()
    now = utc_now()

    # Simulate old v1 database with 16 employees
    with db.transaction(immediate=True) as session:
        v_rec = session.get(SystemMetadataRecord, "demo_employee_fixture_version")
        if v_rec:
            v_rec.value = "1"
        else:
            session.add(SystemMetadataRecord(key="demo_employee_fixture_version", value="1"))
        r_rec = session.get(SystemMetadataRecord, "employee_revision")
        if r_rec:
            r_rec.value = "5"
        else:
            session.add(SystemMetadataRecord(key="employee_revision", value="5"))
        # Add a custom non-demo employee that should never be deleted
        session.add(
            EmployeeRecord(
                id="E99",
                role="clerk",
                skills=["beverage"],
                available_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
                leave_days=[],
                preferred_shift=None,
                created_at=now,
                updated_at=now,
            )
        )

    # First sync: version 1 -> version 2
    updated_count = seed_demo_employees(db)
    assert updated_count == 20  # 20 demo employees synced/upserted

    with db.session() as session:
        fixture_ver = session.get(SystemMetadataRecord, "demo_employee_fixture_version").value
        rev_after = int(session.get(SystemMetadataRecord, "employee_revision").value)
        assert fixture_ver == str(DEMO_EMPLOYEE_FIXTURE_VERSION)
        assert rev_after == 6  # Incremented exactly once from 5 to 6

        # Custom employee E99 is preserved
        assert session.get(EmployeeRecord, "E99") is not None
        # All 20 demo employees present
        all_ids = set(session.scalars(select(EmployeeRecord.id)).all())
        assert {f"E{i:02d}" for i in range(1, 21)}.issubset(all_ids)

    # Second sync: already version 2, must be idempotent
    second_run = seed_demo_employees(db)
    assert second_run == 0

    with db.session() as session:
        rev_subsequent = int(session.get(SystemMetadataRecord, "employee_revision").value)
        assert rev_subsequent == 6  # Revision not incremented on idempotent rerun


def test_canonical_dataset_strict_feasible_schedule(client):
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
    assert payload["compliance_status"] == "compliant"
    assert payload["validation"]["passed"] is True
    assert payload["validation"]["passed_count"] == 10
    assert not payload["validation"]["violations"]


def test_canonical_force_r08_e01_wednesday_morning(client):
    # E01 has leave on Wednesday in canonical dataset
    # Force schedule E01 on Wed morning
    body = {
        "week_start": "2026-09-21",
        "base_schedule_id": None,
        "base_version": None,
        "client_message_id": "force-r08-canonical",
        "force_request": {
            "authorization_reason": "明确授权 E01 周三请假早班上班",
            "requested_overrides": [{"rule_id": "R08", "employee_id": "E01", "day": "Wed", "shift": "morning"}],
            "forced_assignments": [{"employee_id": "E01", "day": "Wed", "shift": "morning"}],
        },
    }
    response = client.post("/api/schedule/force", json=body)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["compliance_status"] == "authorized_violations"
    assert draft["confirmable"] is True
    assert draft["validation"]["passed"] is False
    assert len(draft["validation"]["authorized_violations"]) == 1
    v = draft["validation"]["authorized_violations"][0]
    assert v["rule_id"] == "R08"
    assert v["employee_id"] == "E01"
    assert v["day"] == "Wed"
    assert v["shift"] == "morning"

    # Confirm the forced draft
    confirm_resp = client.post(
        "/api/schedule/confirm",
        json={"schedule_id": draft["schedule_id"], "version": draft["version"]},
    )
    assert confirm_resp.status_code == 200
    confirmed = confirm_resp.json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["compliance_status"] == "authorized_violations"

    # Version history retains authorized violations
    versions_resp = client.get(f"/api/schedules/{draft['schedule_id']}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()["versions"]
    assert versions[0]["authorized_violation_count"] == 1
