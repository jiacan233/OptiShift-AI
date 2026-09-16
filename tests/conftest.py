from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

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

