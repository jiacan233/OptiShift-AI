"""Pure scheduling facts derived from an immutable scheduling context."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from ..models import (
    WEEK_DAYS,
    Assignment,
    ChangeType,
    Day,
    HistoryStatus,
    SchedulingContext,
    Shift,
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
    day_preferences: frozenset[tuple[Day, Shift]] = frozenset()
    available_slots: frozenset[tuple[Day, Shift]] = frozenset()
    unavailable_slots: frozenset[tuple[Day, Shift]] = frozenset()
    forced_workdays: frozenset[Day] = frozenset()
    workday_count: int | None = None
    candidate_days: frozenset[Day] | None = None

    def can_work(self, day: Day, shift: Shift | None = None) -> bool:
        """Resolve an exact slot; a date-only query means any shift is available.

        A slot-specific AVAILABLE is a narrow exception to whole-day policy.
        Explicit slot restrictions still win if a contradictory batch reaches
        the solver. Availability never creates a required assignment.
        """
        if self.candidate_days is not None and day not in self.candidate_days:
            return False
        if shift is None:
            return any(self.can_work(day, candidate) for candidate in Shift)
        if (day, shift) in self.unavailable_slots:
            return False
        if (day, shift) in self.available_slots:
            return True
        return day in self.available_days and day not in self.leave_days

    def preferred_shifts_for(self, day: Day) -> frozenset[Shift]:
        """Explicit date preferences replace the default on that date only.

        Repeated identical requests have no additional weight. If more than
        one shift is preferred on a day, either can earn the day's one reward;
        H01 still forbids working both. Preferences never grant availability.
        """
        explicit = frozenset(
            shift for requested_day, shift in self.day_preferences if requested_day is day
        )
        if explicit:
            return explicit
        return frozenset({self.preferred_shift}) if self.preferred_shift else frozenset()


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
                "day_preferences": set(),
                "available_slots": set(),
                "unavailable_slots": set(),
                "assign": set(),
                "unassign": set(),
                "forced_workdays": set(),
                "workday_count": None,
                "candidate_days": None,
            }

        for change in self.context.requested_changes:
            policy = mutable[change.employee_id]
            if change.type in {ChangeType.LEAVE, ChangeType.UNAVAILABLE}:
                if change.shift is None:
                    policy["leave"].add(change.day)  # type: ignore[union-attr]
                else:
                    policy["unavailable_slots"].add((change.day, change.shift))  # type: ignore[union-attr]
            elif change.type is ChangeType.AVAILABLE:
                if change.shift is None:
                    policy["available"].add(change.day)  # type: ignore[union-attr]
                    policy["leave"].discard(change.day)  # type: ignore[union-attr]
                else:
                    policy["available_slots"].add((change.day, change.shift))  # type: ignore[union-attr]
            elif change.type is ChangeType.PREFERENCE and change.shift is not None:
                policy["day_preferences"].add((change.day, change.shift))  # type: ignore[union-attr]
            elif change.type is ChangeType.ASSIGN:
                if change.shift is not None:
                    policy["assign"].add((change.day, change.shift))  # type: ignore[union-attr]
                else:
                    if change.candidate_days and change.work_day_count is not None:
                        policy["workday_count"] = change.work_day_count
                        policy["candidate_days"] = frozenset(change.candidate_days)
                    elif change.day is not None:
                        policy["forced_workdays"].add(change.day)  # type: ignore[union-attr]
            elif change.type is ChangeType.UNASSIGN and change.shift is not None:
                policy["unassign"].add((change.day, change.shift))  # type: ignore[union-attr]

        return {
            employee_id: EffectiveEmployeePolicy(
                available_days=frozenset(policy["available"]),  # type: ignore[arg-type]
                leave_days=frozenset(policy["leave"]),  # type: ignore[arg-type]
                preferred_shift=policy["preferred"],  # type: ignore[arg-type]
                forced_assignments=frozenset(policy["assign"]),  # type: ignore[arg-type]
                forced_unassignments=frozenset(policy["unassign"]),  # type: ignore[arg-type]
                day_preferences=frozenset(policy["day_preferences"]),  # type: ignore[arg-type]
                available_slots=frozenset(policy["available_slots"]),  # type: ignore[arg-type]
                unavailable_slots=frozenset(policy["unavailable_slots"]),  # type: ignore[arg-type]
                forced_workdays=frozenset(policy["forced_workdays"]),  # type: ignore[arg-type]
                workday_count=policy["workday_count"],  # type: ignore[arg-type]
                candidate_days=policy["candidate_days"],  # type: ignore[arg-type]
            )
            for employee_id, policy in mutable.items()
        }

    def employee_can_work(self, employee_id: str, day: Day, shift: Shift | None = None) -> bool:
        return self.policies[employee_id].can_work(day, shift)

    def preference_keys(self) -> tuple[tuple[str, Day, Shift], ...]:
        """Return stable, deduplicated reward slots for both solver and metrics."""
        return tuple(
            (employee.id, day, shift)
            for employee in self.context.employees
            for day in WEEK_DAYS
            for shift in Shift
            if shift in self.policies[employee.id].preferred_shifts_for(day)
        )

    def preference_metrics(self, assignments: list[Assignment]) -> dict[str, int | float | str]:
        """Count rewards against the effective employee-day preference set.

        An unscheduled preferred day is unsatisfied, rather than disappearing
        from the denominator. A day contributes at most one opportunity and
        one reward, consistent with H01 and the solver's objective. Explicit
        date requests also have separate counters so a default preference
        elsewhere in the week cannot conceal an unsatisfied date request.
        """
        preference_keys = set(self.preference_keys())
        actual = {(item.employee_id, item.day, item.shift) for item in assignments}
        opportunities = {(employee_id, day) for employee_id, day, _ in preference_keys}
        satisfied = {(employee_id, day) for employee_id, day, _ in actual & preference_keys}
        explicit_keys = {
            (employee_id, day, shift)
            for employee_id, policy in self.policies.items()
            for day, shift in policy.day_preferences
        }
        explicit_opportunities = {(employee_id, day) for employee_id, day, _ in explicit_keys}
        explicit_satisfied = {
            (employee_id, day) for employee_id, day, _ in actual & explicit_keys
        }
        return {
            "preference_satisfied": len(satisfied),
            "preference_opportunities": len(opportunities),
            "preference_rate": len(satisfied) / len(opportunities) if opportunities else 1.0,
            "preference_scope": "effective_employee_days",
            "day_preference_satisfied": len(explicit_satisfied),
            "day_preference_opportunities": len(explicit_opportunities),
            "day_preference_rate": (
                len(explicit_satisfied) / len(explicit_opportunities)
                if explicit_opportunities else 1.0
            ),
        }

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

    def following_work_vector(self, employee_id: str) -> list[int]:
        """Return enough of the next week for its own R06 limit, oldest first."""
        length = min(7, self.context.following_max_consecutive_days or
                     self.context.rules.max_consecutive_days)
        dated = {
            item.assignment_date for item in self.context.following_days
            if item.employee_id == employee_id and item.assignment_date is not None
        }
        if self.week_start is not None and dated:
            return [
                int(self.week_start + timedelta(days=offset) in dated)
                for offset in range(7, 7 + length)
            ]
        worked_days = {
            item.day for item in self.context.following_days if item.employee_id == employee_id
        }
        return [int(day in worked_days) for day in WEEK_DAYS[:length]]

    def r06_windows(self, previous_length: int, timeline_length: int) -> Iterator[tuple[int, int, int]]:
        """Use this week's limit until Sunday and the successor's across Sunday."""
        current_end = previous_length + len(WEEK_DAYS)
        current_maximum = self.context.rules.max_consecutive_days
        following_maximum = self.context.following_max_consecutive_days or current_maximum
        for maximum in dict.fromkeys((current_maximum, following_maximum)):
            for start in range(timeline_length - maximum):
                end = start + maximum + 1
                if end <= previous_length or start >= current_end:
                    continue
                applicable_maximum = following_maximum if end > current_end else current_maximum
                if maximum == applicable_maximum:
                    yield start, end, maximum

    def following_monday_morning(self, employee_id: str) -> int:
        dated = [
            item for item in self.context.following_days
            if item.employee_id == employee_id and item.assignment_date is not None
        ]
        if self.week_start is not None and dated:
            return int(any(
                item.assignment_date == self.week_start + timedelta(days=7)
                and item.shift is Shift.MORNING for item in dated
            ))
        return int(any(
            item.employee_id == employee_id and item.day is Day.MON
            and item.shift is Shift.MORNING for item in self.context.following_days
        ))

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
