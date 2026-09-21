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
from backend.app.services.agent_router import AgentRouter
from backend.app.solver import PrimarySolver
from backend.app.validator import RuleValidator
from backend.app.validator.authorization import classify_validation

CANONICAL_SPEC: dict[str, dict] = {
    "E01": {
        "role": "manager",
        "skills": ["manager", "beverage", "cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Wed"],
        "preferred_shift": "morning",
    },
    "E02": {
        "role": "vice_manager",
        "skills": ["manager", "beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    "E03": {
        "role": "shift_leader",
        "skills": ["manager", "beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "leave_days": [],
        "preferred_shift": None,
    },
    "E04": {
        "role": "shift_leader",
        "skills": ["manager", "beverage", "inventory"],
        "available_days": ["Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    "E05": {
        "role": "senior_clerk",
        "skills": ["manager", "beverage", "cashier"],
        "available_days": ["Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    "E06": {
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Tue"],
        "preferred_shift": "morning",
    },
    "E07": {
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    "E08": {
        "role": "clerk",
        "skills": ["beverage", "cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "leave_days": [],
        "preferred_shift": None,
    },
    "E09": {
        "role": "clerk",
        "skills": ["beverage"],
        "available_days": ["Mon", "Wed", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    "E10": {
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    "E11": {
        "role": "clerk",
        "skills": ["cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    "E12": {
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    "E13": {
        "role": "part_time",
        "skills": ["beverage"],
        "available_days": ["Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    "E14": {
        "role": "part_time",
        "skills": ["beverage", "cashier"],
        "available_days": ["Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    "E15": {
        "role": "part_time",
        "skills": ["cashier"],
        "available_days": ["Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    "E16": {
        "role": "part_time",
        "skills": ["beverage"],
        "available_days": ["Wed", "Thu", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    "E17": {
        "role": "clerk",
        "skills": ["beverage", "cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Mon"],
        "preferred_shift": None,
    },
    "E18": {
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    "E19": {
        "role": "part_time",
        "skills": ["beverage", "cashier"],
        "available_days": ["Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    "E20": {
        "role": "clerk",
        "skills": ["beverage", "inventory"],
        "available_days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Thu"],
        "preferred_shift": "morning",
    },
}


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

    # Field-by-field verification for all 20 employees against canonical spec
    for emp_id, spec in CANONICAL_SPEC.items():
        assert emp_id in employees, f"Missing employee {emp_id}"
        emp = employees[emp_id]
        assert emp["role"] == spec["role"], f"{emp_id} role mismatch"
        assert set(emp["skills"]) == set(spec["skills"]), f"{emp_id} skills mismatch"
        assert emp["available_days"] == spec["available_days"], f"{emp_id} available_days mismatch"
        assert emp["leave_days"] == spec["leave_days"], f"{emp_id} leave_days mismatch"
        assert emp["preferred_shift"] == spec["preferred_shift"], f"{emp_id} preferred_shift mismatch"

    # Explicit verification of mandatory exam checkpoints
    assert employees["E01"]["leave_days"] == ["Wed"]
    assert employees["E06"]["leave_days"] == ["Tue"]
    assert employees["E17"]["leave_days"] == ["Mon"]
    assert employees["E20"]["leave_days"] == ["Thu"]

    # Explicit skill checkpoints
    assert set(employees["E02"]["skills"]) == {"manager", "beverage", "cashier"}
    assert "manager" in employees["E05"]["skills"]
    assert "beverage" not in employees["E11"]["skills"] and set(employees["E11"]["skills"]) == {"cashier", "inventory"}
    assert set(employees["E15"]["skills"]) == {"cashier"}
    assert set(employees["E16"]["skills"]) == {"beverage"}
    assert "cashier" not in employees["E20"]["skills"] and set(employees["E20"]["skills"]) == {"beverage", "inventory"}


def test_versioned_demo_sync_idempotence_and_upgrade(tmp_path):
    from backend.app.database import utc_now

    db_path = tmp_path / "upgrade-test.db"
    db = Database(db_path)
    db.initialize()
    now = utc_now()

    # Simulate an old fixture version containing an employee created by the
    # former dynamic employee flow.
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
        # Add a non-canonical employee that the closed-roster upgrade must delete.
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

    # First sync: old version -> closed-roster fixture version.
    updated_count = seed_demo_employees(db)
    assert updated_count == 21  # 20 canonical upserts plus the E99 deletion.

    with db.session() as session:
        fixture_ver = session.get(SystemMetadataRecord, "demo_employee_fixture_version").value
        rev_after = int(session.get(SystemMetadataRecord, "employee_revision").value)
        assert fixture_ver == str(DEMO_EMPLOYEE_FIXTURE_VERSION)
        assert rev_after == 6  # Incremented exactly once from 5 to 6

        assert session.get(EmployeeRecord, "E99") is None
        all_ids = set(session.scalars(select(EmployeeRecord.id)).all())
        assert all_ids == {f"E{i:02d}" for i in range(1, 21)}

    # Second sync: already at the current version, must be idempotent.
    second_run = seed_demo_employees(db)
    assert second_run == 0

    with db.session() as session:
        rev_subsequent = int(session.get(SystemMetadataRecord, "employee_revision").value)
        assert rev_subsequent == 6  # Revision not incremented on idempotent rerun

    # Subsequent sync does not overwrite user-modified fields once the fixture
    # is already current.
    with db.transaction() as session:
        e01_rec = session.get(EmployeeRecord, "E01")
        e01_rec.preferred_shift = "evening"
        e01_rec.updated_at = now

    third_run = seed_demo_employees(db)
    assert third_run == 0

    with db.session() as session:
        e01_persisted = session.get(EmployeeRecord, "E01")
        assert e01_persisted.preferred_shift == "evening"  # User modification preserved!


def test_canonical_dataset_strict_feasible_schedule(client):
    response = client.post(
        "/api/schedule/generate",
        json={
            "week_start": "2026-09-21",
            "prompt": "",
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

    assignments = payload["schedule"]["assignments"]
    # Verify leave days strictly respected in compliant mode
    assert not any(a["employee_id"] == "E01" and a["day"] == "Wed" for a in assignments), "E01 scheduled on Wed leave"
    assert not any(a["employee_id"] == "E06" and a["day"] == "Tue" for a in assignments), "E06 scheduled on Tue leave"
    assert not any(a["employee_id"] == "E17" and a["day"] == "Mon" for a in assignments), "E17 scheduled on Mon leave"
    assert not any(a["employee_id"] == "E20" and a["day"] == "Thu" for a in assignments), "E20 scheduled on Thu leave"


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
