"""Pure scheduling facts derived from an immutable scheduling context."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from ..models import (
    Assignment,
    ChangeType,
    Day,
    Employee,
    HistoryStatus,
    SchedulingContext,
    Shift,
    WEEK_DAYS,
)


class HistoryUnavailableError(ValueError):
    """Raised when cross-week hard constraints cannot be evaluated safely."""


@dataclass(frozen=True)
class EffectiveEmployeePolicy:
    available_days: frozenset[Day]
    leave_days: frozenset[Day]
    preferred_shift: Shift | None
    forced_assignments: frozenset[tuple[Day, Shift]]
    forced_unassignments: frozenset[tuple[Day, Shift]]

    def can_work(self, day: Day) -> bool:
        return day in self.available_days and day not in self.leave_days


class SchedulingFacts:
    """Read-only, deterministic interpretation of context and requested changes."""

    def __init__(self, context: SchedulingContext, week_start: date | None = None) -> None:
        if context.history_status is HistoryStatus.UNAVAILABLE:
            raise HistoryUnavailableError(
                "Previous-week history is unavailable; R06 and R07 cannot be evaluated safely."
            )
        self.context = context
        self.week_start = week_start or (
            context.base_schedule.week_start if context.base_schedule is not None else None
        )
        self.employees = {employee.id: employee for employee in context.employees}
        self.policies = self._build_policies()

    def _build_policies(self) -> dict[str, EffectiveEmployeePolicy]:
        mutable: dict[str, dict[str, object]] = {}
        for employee in self.context.employees:
            mutable[employee.id] = {
                "available": set(employee.available_days),
                "leave": set(employee.leave_days),
                "preferred": employee.preferred_shift,
                "assign": set(),
                "unassign": set(),
            }

        for change in self.context.requested_changes:
            policy = mutable[change.employee_id]
            if change.type in {ChangeType.LEAVE, ChangeType.UNAVAILABLE}:
                policy["leave"].add(change.day)  # type: ignore[union-attr]
            elif change.type is ChangeType.AVAILABLE:
                policy["available"].add(change.day)  # type: ignore[union-attr]
                policy["leave"].discard(change.day)  # type: ignore[union-attr]
            elif change.type is ChangeType.PREFERENCE:
                policy["preferred"] = change.shift
            elif change.type is ChangeType.ASSIGN and change.shift is not None:
                policy["assign"].add((change.day, change.shift))  # type: ignore[union-attr]
            elif change.type is ChangeType.UNASSIGN and change.shift is not None:
                policy["unassign"].add((change.day, change.shift))  # type: ignore[union-attr]

        return {
            employee_id: EffectiveEmployeePolicy(
                available_days=frozenset(policy["available"]),  # type: ignore[arg-type]
                leave_days=frozenset(policy["leave"]),  # type: ignore[arg-type]
                preferred_shift=policy["preferred"],  # type: ignore[arg-type]
                forced_assignments=frozenset(policy["assign"]),  # type: ignore[arg-type]
                forced_unassignments=frozenset(policy["unassign"]),  # type: ignore[arg-type]
            )
            for employee_id, policy in mutable.items()
        }

    def employee_can_work(self, employee_id: str, day: Day) -> bool:
        return self.policies[employee_id].can_work(day)

    def base_assignment_keys(self) -> set[tuple[str, Day, Shift]]:
        if self.context.base_schedule is None:
            return set()
        return {
            (assignment.employee_id, assignment.day, assignment.shift)
            for assignment in self.context.base_schedule.assignments
        }

    def previous_work_vector(self, employee_id: str) -> list[int]:
        """Return the five days immediately before the target Monday, oldest first."""

        if self.context.history_status is HistoryStatus.KNOWN_EMPTY:
            return [0, 0, 0, 0, 0]

        worked_dates: set[date] = set()
        if self.week_start is not None:
            for item in self.context.previous_days:
                if item.employee_id == employee_id and item.assignment_date is not None:
                    worked_dates.add(item.assignment_date)
            if worked_dates:
                return [
                    int(self.week_start - timedelta(days=offset) in worked_dates)
                    for offset in range(5, 0, -1)
                ]

        # The last five weekdays before Monday are Wed, Thu, Fri, Sat, Sun.
        boundary_days = WEEK_DAYS[-5:]
        worked_days = {
            item.day for item in self.context.previous_days if item.employee_id == employee_id
        }
        return [int(day in worked_days) for day in boundary_days]

    def previous_sunday_evening(self, employee_id: str) -> int:
        if self.context.history_status is HistoryStatus.KNOWN_EMPTY:
            return 0
        if self.week_start is not None:
            previous_sunday = self.week_start - timedelta(days=1)
            dated = [
                item
                for item in self.context.previous_days
                if item.employee_id == employee_id and item.assignment_date is not None
            ]
            if dated:
                return int(
                    any(
                        item.assignment_date == previous_sunday and item.shift is Shift.EVENING
                        for item in dated
                    )
                )
        return int(
            any(
                item.employee_id == employee_id
                and item.day is Day.SUN
                and item.shift is Shift.EVENING
                for item in self.context.previous_days
            )
        )

    @staticmethod
    def assignment_index(
        assignments: list[Assignment],
    ) -> dict[tuple[str, Day, Shift], int]:
        counts: dict[tuple[str, Day, Shift], int] = defaultdict(int)
        for assignment in assignments:
            counts[(assignment.employee_id, assignment.day, assignment.shift)] += 1
        return counts

    @staticmethod
    def employee_day_shifts(
        assignments: list[Assignment],
    ) -> dict[tuple[str, Day], list[Shift]]:
        result: dict[tuple[str, Day], list[Shift]] = defaultdict(list)
        for assignment in assignments:
            result[(assignment.employee_id, assignment.day)].append(assignment.shift)
        return result
