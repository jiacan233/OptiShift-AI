from __future__ import annotations

from datetime import date, timedelta

from ..models import (
    Employee,
    HistoricalAssignment,
    RuleConfig,
    Schedule,
    ScheduleChange,
    SchedulingContext,
)
from ..repository import EmployeeRepository, ScheduleRepository


DAY_OFFSETS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


class ContextBuilder:
    def __init__(
        self,
        employees: EmployeeRepository,
        schedules: ScheduleRepository,
        rules: RuleConfig | None = None,
    ) -> None:
        self.employee_repository = employees
        self.schedule_repository = schedules
        self.rules = rules or RuleConfig()

    def build(
        self,
        week_start: date,
        *,
        base_schedule: Schedule | None = None,
        changes: list[ScheduleChange] | None = None,
        minimize_changes: bool = False,
        employees: list[Employee] | None = None,
        allow_history_bootstrap: bool = True,
        allow_ephemeral_known_empty: bool = False,
    ) -> SchedulingContext:
        previous, history_status = self.schedule_repository.previous_week_context(
            week_start,
            allow_bootstrap=allow_history_bootstrap,
            allow_ephemeral_known_empty=allow_ephemeral_known_empty,
        )
        history = []
        if previous is not None:
            for assignment in previous.assignments:
                history.append(
                    HistoricalAssignment(
                        employee_id=assignment.employee_id,
                        day=assignment.day,
                        shift=assignment.shift,
                        assignment_date=previous.week_start
                        + timedelta(days=DAY_OFFSETS[assignment.day.value]),
                    )
                )
        return SchedulingContext(
            base_schedule=base_schedule,
            previous_days=history,
            history_schedule_id=(previous.schedule_id if previous is not None else None),
            history_schedule_version=(previous.version if previous is not None else None),
            employees=(
                employees
                if employees is not None
                else self.employee_repository.list_with_revision()[0]
            ),
            rules=self.rules,
            requested_changes=changes or [],
            history_status=history_status,
            minimize_changes=minimize_changes,
        )
