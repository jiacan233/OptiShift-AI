from __future__ import annotations

from typing import Any

from ..database import database
from ..repository import EmployeeRepository, ScheduleRepository
from ..services.scheduling_service import SchedulingService


employee_repository = EmployeeRepository(database)
schedule_repository = ScheduleRepository(database)
scheduling_service = SchedulingService(employee_repository, schedule_repository)

# Clarifications are short-lived UI interactions. Core schedules and versions remain in SQLite.
pending_clarifications: dict[str, dict[str, Any]] = {}

