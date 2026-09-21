from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date

import pytest

# Tests must never inherit a production dotenv/shell setting.  This runs before
# importing application modules, whose global Database instance reads APP_ENV.
os.environ["APP_ENV"] = "test"

from backend.app.database import Database, seed_demo_employees
from backend.app.models import (
    Day,
    Employee,
    HistoryStatus,
    RuleConfig,
    SchedulingContext,
    Shift,
    Skill,
    WEEK_DAYS,
)
from backend.app.repository import EmployeeRepository, ScheduleRepository
from backend.app.services.scheduling_service import SchedulingService


EmployeeFactory = Callable[..., Employee]


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test on the local SQLite-safe environment."""
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture
def week_start() -> date:
    return date(2026, 9, 21)


@pytest.fixture
def employee_factory() -> EmployeeFactory:
    def make_employee(
        employee_id: str,
        *,
        role: str = "full_time",
        skills: list[Skill] | None = None,
        available_days: list[Day] | None = None,
        leave_days: list[Day] | None = None,
        preferred_shift: Shift | None = None,
    ) -> Employee:
        return Employee(
            id=employee_id,
            role=role,
            skills=list(skills if skills is not None else Skill),
            available_days=list(available_days if available_days is not None else WEEK_DAYS),
            leave_days=list(leave_days or []),
            preferred_shift=preferred_shift,
        )

    return make_employee


@pytest.fixture
def balanced_employees(employee_factory: EmployeeFactory) -> list[Employee]:
    return [
        employee_factory(
            f"E{index:02d}",
            role="manager" if index <= 4 else "full_time",
            preferred_shift=Shift.MORNING if index % 2 else Shift.EVENING,
        )
        for index in range(1, 17)
    ]


@pytest.fixture
def default_context(balanced_employees: list[Employee]) -> SchedulingContext:
    return SchedulingContext(
        employees=balanced_employees,
        rules=RuleConfig(max_time_seconds=5, random_seed=42, num_search_workers=1),
        history_status=HistoryStatus.KNOWN_EMPTY,
    )


@pytest.fixture
def database(tmp_path) -> Database:
    value = Database(tmp_path / "optishift-test.db")
    value.initialize()
    return value


@pytest.fixture
def repositories(database: Database) -> tuple[EmployeeRepository, ScheduleRepository]:
    return EmployeeRepository(database), ScheduleRepository(database)


@pytest.fixture
def demo_service(database: Database) -> SchedulingService:
    seed_demo_employees(database)
    return SchedulingService(EmployeeRepository(database), ScheduleRepository(database))


@pytest.fixture
def semantic_reply(monkeypatch):
    """Script provider DTOs, never parse text. Real language evaluations run separately."""
    from backend.app.models.dialogue import TurnCommand
    from backend.app.services.llm_client import AIUnavailableError

    def install(*plans, service=None):
        if service is None:
            from backend.app.api.dependencies import agent_service
            service = agent_service
        remaining = iter(plans)
        calls = []
        def reply(**kwargs):
            name = kwargs.get("schema_name")
            calls.append(name)
            if name == "agent_semantic_verifier":
                return {"valid": True, "clarification": None}
            if name not in {"agent_semantic", "agent_semantic_repair"}:
                raise AIUnavailableError("No optional composition in offline tests")
            value = plans[0] if len(plans) == 1 and callable(plans[0]) else next(remaining)
            if callable(value):
                value = value(kwargs["user"])
            command = value if isinstance(value, TurnCommand) else TurnCommand.model_validate(value)
            command.declared_condition_count = len(command.edits) + len(command.staffing_constraints)
            return command.model_dump(mode="json")
        def no_composition(**kwargs):
            raise AIUnavailableError("No optional composition in offline tests")
        monkeypatch.setattr(service.llm, "enabled", True)
        monkeypatch.setattr(service.llm, "complete_json", reply)
        monkeypatch.setattr(service.llm, "complete_text", no_composition)
        return calls
    return install
