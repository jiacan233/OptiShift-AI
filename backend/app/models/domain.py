"""Strongly typed domain contracts for workforce scheduling.

The solver, validator, services, and API all exchange these models.  Keeping
the contracts here prevents the optimisation code from becoming the source
of truth for business data.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StringEnum(str, Enum):
    """Enum whose values serialize as the public API strings."""

    def __str__(self) -> str:
        return self.value


class Day(StringEnum):
    MON = "Mon"
    TUE = "Tue"
    WED = "Wed"
    THU = "Thu"
    FRI = "Fri"
    SAT = "Sat"
    SUN = "Sun"


WEEK_DAYS: tuple[Day, ...] = (
    Day.MON,
    Day.TUE,
    Day.WED,
    Day.THU,
    Day.FRI,
    Day.SAT,
    Day.SUN,
)


class Shift(StringEnum):
    MORNING = "morning"
    EVENING = "evening"


SHIFTS: tuple[Shift, ...] = (Shift.MORNING, Shift.EVENING)


class StaffingScope(StringEnum):
    """The unit over which a headcount constraint is evaluated."""

    DAY = "DAY"
    SHIFT = "SHIFT"


class Skill(StringEnum):
    MANAGER = "manager"
    BEVERAGE = "beverage"
    CASHIER = "cashier"
    INVENTORY = "inventory"


class ScheduleStatus(StringEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class RequestIntent(StringEnum):
    GENERATE = "generate"
    REPLAN = "replan"
    VALIDATE = "validate"


class PatchOperation(StringEnum):
    SET = "set"
    ADD = "add"
    REMOVE = "remove"
    CLEAR = "clear"


class ChangeType(StringEnum):
    LEAVE = "leave"
    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"
    PREFERENCE = "preference"
    ASSIGN = "assign"
    UNASSIGN = "unassign"


class HistoryStatus(StringEnum):
    KNOWN_EMPTY = "known_empty"
    UNAVAILABLE = "history_unavailable"
    AVAILABLE = "history_available"


class SolverStatus(StringEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    MODEL_INVALID = "model_invalid"


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
    )


class Employee(StrictModel):
    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    skills: list[Skill]
    available_days: list[Day]
    leave_days: list[Day] = Field(default_factory=list)
    preferred_shift: Shift | None = None

    @field_validator("skills", "available_days", "leave_days")
    @classmethod
    def values_must_be_unique(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values


class Assignment(StrictModel):
    employee_id: str = Field(min_length=1)
    day: Day
    shift: Shift


class HistoricalAssignment(StrictModel):
    """A real assignment from an adjacent confirmed schedule.

    ``assignment_date`` is preferred because it preserves chronology.  ``day``
    remains required for a compact API and for seeded demo boundaries.
    """

    employee_id: str = Field(min_length=1)
    day: Day
    shift: Shift
    assignment_date: date | None = None


class Schedule(StrictModel):
    schedule_id: str = Field(default_factory=lambda: f"sch_{uuid4().hex[:12]}")
    version: int = Field(default=1, ge=1)
    parent_schedule_id: str | None = None
    status: ScheduleStatus = ScheduleStatus.DRAFT
    week_start: date
    assignments: list[Assignment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScheduleChange(StrictModel):
    employee_id: str = Field(min_length=1)
    type: ChangeType
    day: Day
    shift: Shift | None = None

    @model_validator(mode="after")
    def require_shift_when_needed(self) -> "ScheduleChange":
        if self.type in {ChangeType.PREFERENCE, ChangeType.ASSIGN, ChangeType.UNASSIGN}:
            if self.shift is None:
                raise ValueError(f"shift is required for change type {self.type.value}")
        return self


class ScheduleRequest(StrictModel):
    intent: RequestIntent
    base_schedule_id: str | None = None
    base_version: int | None = Field(default=None, ge=1)
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = False

    @model_validator(mode="after")
    def replan_requires_base_identity(self) -> "ScheduleRequest":
        if self.intent is RequestIntent.REPLAN:
            if self.base_schedule_id is None or self.base_version is None:
                raise ValueError("replan requires base_schedule_id and base_version")
        return self


class ObjectiveWeights(StrictModel):
    preference_reward: int = Field(default=5, ge=0)
    workload_gap_penalty: int = Field(default=2, ge=0)
    schedule_change_penalty: int = Field(default=8, ge=0)


class StaffingConstraint(StrictModel):
    """A normalized staffing requirement supplied by a scheduling request.

    ``days`` and ``shifts`` scope the constraint to the supplied week.  A DAY
    constraint counts all assignments on a day, while SHIFT counts one shift
    at a time.  ``target_count`` is a soft target unless it is accompanied by
    equal min/max values (the exact form produced for "就 N 人" requests).
    """

    scope: StaffingScope
    days: list[Day] = Field(default_factory=list)
    shifts: list[Shift] = Field(default_factory=list)
    min_count: int | None = Field(default=None, ge=0, strict=True)
    target_count: int | None = Field(default=None, ge=0, strict=True)
    max_count: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_bounds(self) -> "StaffingConstraint":
        if self.min_count is None and self.target_count is None and self.max_count is None:
            raise ValueError("staffing constraint requires min_count, target_count or max_count")
        if self.min_count is not None and self.max_count is not None and self.min_count > self.max_count:
            raise ValueError("staffing constraint min_count cannot exceed max_count")
        if self.target_count is not None:
            if self.min_count is not None and self.target_count < self.min_count:
                raise ValueError("staffing target cannot be below min_count")
            if self.max_count is not None and self.target_count > self.max_count:
                raise ValueError("staffing target cannot exceed max_count")
        return self

    def applies(self, day: Day, shift: Shift | None = None) -> bool:
        if self.days and day not in self.days:
            return False
        if self.scope is StaffingScope.DAY:
            return shift is None
        return shift is not None and (not self.shifts or shift in self.shifts)


class RuleConfig(StrictModel):
    manager_per_shift: int = Field(default=1, ge=0)
    beverage_per_shift: int = Field(default=2, ge=0)
    cashier_per_shift: int = Field(default=1, ge=0)
    weekday_min_staff: int = Field(default=4, ge=0)
    weekend_min_staff: int = Field(default=6, ge=0)
    staffing_constraints: list[StaffingConstraint] = Field(default_factory=list)
    max_shifts_per_week: int = Field(default=5, ge=0)
    max_consecutive_days: int = Field(default=5, ge=1)
    max_time_seconds: float = Field(default=8.0, gt=0)
    random_seed: int = 2026
    num_search_workers: int = Field(default=1, ge=1)
    objective: ObjectiveWeights = Field(default_factory=ObjectiveWeights)

    def minimum_staff(self, day: Day, shift: Shift | None = None) -> int:
        default = self.weekend_min_staff if day in {Day.SAT, Day.SUN} else self.weekday_min_staff
        constraints = self.staffing_for(day, shift) if shift is not None else []
        minimums = [c.min_count for c in constraints if c.min_count is not None]
        maximums = [c.max_count for c in constraints if c.max_count is not None]
        # Explicit SHIFT bounds replace the default headcount, never skill or
        # work/rest rules. A soft target alone keeps the default minimum.
        return max(minimums) if minimums else min([default, *maximums])

    def staffing_for(self, day: Day, shift: Shift | None = None) -> list[StaffingConstraint]:
        """Return request-scoped constraints matching a day/shift unit."""
        return [item for item in self.staffing_constraints if item.applies(day, shift)]


class SchedulingContext(StrictModel):
    user_forced_assignments: list[Assignment] = Field(default_factory=list)
    override_scopes: list[dict[str, Any]] = Field(default_factory=list)
    base_schedule: Schedule | None = None
    previous_days: list[HistoricalAssignment] = Field(default_factory=list)
    following_days: list[HistoricalAssignment] = Field(default_factory=list)
    following_schedule_id: str | None = None
    following_schedule_version: int | None = Field(default=None, ge=1)
    following_max_consecutive_days: int | None = Field(default=None, ge=1)
    history_schedule_id: str | None = None
    history_schedule_version: int | None = Field(default=None, ge=1)
    employees: list[Employee]
    rules: RuleConfig = Field(default_factory=RuleConfig)
    requested_changes: list[ScheduleChange] = Field(default_factory=list)
    staffing_constraints: list[StaffingConstraint] = Field(default_factory=list)
    history_status: HistoryStatus = HistoryStatus.KNOWN_EMPTY
    minimize_changes: bool = False

    @model_validator(mode="after")
    def validate_context_references(self) -> "SchedulingContext":
        employee_ids = [employee.id for employee in self.employees]
        if len(employee_ids) != len(set(employee_ids)):
            raise ValueError("employee ids must be unique")
        known = set(employee_ids)
        if any(item.employee_id not in known for item in self.user_forced_assignments):
            raise ValueError("Forced assignment references an unknown employee")
        for scope in self.override_scopes:
            if scope.get("employee_id") and scope["employee_id"] not in known:
                raise ValueError("Override scope references an unknown employee")
        unknown_changes = sorted(
            {change.employee_id for change in self.requested_changes if change.employee_id not in known}
        )
        if unknown_changes:
            raise ValueError(f"requested changes reference unknown employees: {unknown_changes}")
        unknown_history = sorted(
            {item.employee_id for item in self.previous_days if item.employee_id not in known}
        )
        if unknown_history:
            raise ValueError(f"history references unknown employees: {unknown_history}")
        if self.history_status is HistoryStatus.KNOWN_EMPTY and self.previous_days:
            raise ValueError("known_empty history cannot contain assignments")
        return self


class RuleViolation(StrictModel):
    rule_id: str
    message: str
    day: Day | None = None
    shift: Shift | None = None
    employee_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RuleCheck(StrictModel):
    passed: bool
    violations: list[RuleViolation] = Field(default_factory=list)


class ValidationResult(StrictModel):
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    valid: bool
    hard_constraints: dict[str, RuleCheck]
    violations: list[RuleViolation] = Field(default_factory=list)
    passed_count: int
    total_count: int = 10


class CapacityConflict(StrictModel):
    rule_id: Literal["R01", "R02", "R03", "R04"]
    day: Day
    shift: Shift
    required: int
    available: int
    shortage: int
    message: str


class DiagnosticConflict(StrictModel):
    rule_id: Literal["R01", "R02", "R03", "R04"]
    day: Day
    shift: Shift
    required: int
    actual: int
    shortage: int


class BlockingReason(StrictModel):
    rule_id: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CandidateBlocking(StrictModel):
    employee_id: str
    day: Day
    shift: Shift
    coverage_rule_id: str
    reasons: list[BlockingReason]


class DiagnosisResult(StrictModel):
    primary_status: SolverStatus = SolverStatus.INFEASIBLE
    capacity_conflicts: list[CapacityConflict] = Field(default_factory=list)
    diagnostic_status: SolverStatus = SolverStatus.UNKNOWN
    diagnostic_conflicts: list[DiagnosticConflict] = Field(default_factory=list)
    blocking_candidates: list[CandidateBlocking] = Field(default_factory=list)
    protected_conflicts: list[RuleViolation] = Field(default_factory=list)
    summary: str
    generated_valid_schedule: Literal[False] = False
    preview_schedule: Schedule | None = None
    minimum_shortage: int = 0
    coverage_gaps: list[dict[str, Any]] = Field(default_factory=list)


class SolverResult(StrictModel):
    status: SolverStatus
    schedule: Schedule | None = None
    objective_value: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    diagnosis: DiagnosisResult | None = None
    message: str | None = None


class ScenarioPatch(StrictModel):
    employee_id: str = Field(min_length=1)
    operation: PatchOperation = PatchOperation.ADD
    days: list[Day] = Field(default_factory=list)
    change_type: ChangeType = ChangeType.LEAVE
    shift: Shift | None = None

    @model_validator(mode="after")
    def require_shift_when_needed(self) -> "ScenarioPatch":
        if self.change_type in {ChangeType.PREFERENCE, ChangeType.ASSIGN, ChangeType.UNASSIGN} and self.shift is None:
            raise ValueError("该条件需要明确早班或晚班")
        return self

    @field_validator("days")
    @classmethod
    def unique_days(cls, values: list[Day]) -> list[Day]:
        if len(values) != len(set(values)):
            raise ValueError("days must be unique")
        return values


class ScenarioState(StrictModel):
    conversation_id: str
    week_start: date
    revision: int = Field(default=0, ge=0)
    patches: list[ScenarioPatch] = Field(default_factory=list)
    updated_at: datetime | None = None
    invalidated: bool = False
    message: str | None = None


class ScenarioPreview(StrictModel):
    status: Literal["scenario_preview"] = "scenario_preview"
    target_week: date
    scenario_revision: int = Field(ge=0)
    strict_feasible: bool
    schedule: Schedule | None = None
    preview_schedule: Schedule | None = None
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    coverage_gaps: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    message: str
