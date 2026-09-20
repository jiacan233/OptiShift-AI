from __future__ import annotations

from datetime import date, timedelta
from typing import Any

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
        user_forced_assignments: list[Any] | None = None,
        override_scopes: list[dict[str, Any]] | None = None,
        rule_config: dict[str, Any] | None = None,
        staffing_constraints: list[Any] | None = None,
    ) -> SchedulingContext:
        if rule_config is None and base_schedule is not None:
            record = self.schedule_repository.get_record(base_schedule.schedule_id)
            rule_config = (record or {}).get("metadata", {}).get("rule_config")
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
        following_record = self.schedule_repository.current_confirmed_record_for_week(
            week_start + timedelta(days=7)
        )
        following = following_record["schedule"] if following_record else None
        following_rules = (
            RuleConfig.model_validate(following_record["metadata"].get("rule_config") or
                                      self.rules.model_dump())
            if following_record else None
        )
        following_days = [
            HistoricalAssignment(
                employee_id=assignment.employee_id,
                day=assignment.day,
                shift=assignment.shift,
                assignment_date=following.week_start
                + timedelta(days=DAY_OFFSETS[assignment.day.value]),
            )
            for assignment in following.assignments
        ] if following is not None else []
        effective_rules = RuleConfig.model_validate(rule_config) if rule_config else self.rules
        if staffing_constraints is not None:
            effective_rules = effective_rules.model_copy(update={"staffing_constraints": staffing_constraints})
        return SchedulingContext(
            base_schedule=base_schedule,
            previous_days=history,
            following_days=following_days,
            following_schedule_id=following.schedule_id if following else None,
            following_schedule_version=following.version if following else None,
            following_max_consecutive_days=(
                following_rules.max_consecutive_days if following_rules else None
            ),
            history_schedule_id=(previous.schedule_id if previous is not None else None),
            history_schedule_version=(previous.version if previous is not None else None),
            employees=(
                employees
                if employees is not None
                else self.employee_repository.list_with_revision()[0]
            ),
            rules=effective_rules,
            staffing_constraints=list(effective_rules.staffing_constraints),
            requested_changes=changes or [],
            history_status=history_status,
            minimize_changes=minimize_changes,
            user_forced_assignments=user_forced_assignments or [],
            override_scopes=override_scopes or [],
        )
