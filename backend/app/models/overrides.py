"""Request-scoped exceptions. These never change employee or rule data."""
from datetime import date, datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .domain import Assignment, Day, Shift, StrictModel, StringEnum


class ComplianceStatus(StringEnum):
    COMPLIANT = "compliant"
    AUTHORIZED_VIOLATIONS = "authorized_violations"
    INVALID = "invalid"


class OverrideScope(StrictModel):
    rule_id: Literal["R01", "R02", "R03", "R04", "R08"]
    day: Day
    shift: Shift
    employee_id: str | None = None
    allowed_shortage: int | None = Field(default=None, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def precise_scope(self):
        if self.rule_id == "R08":
            if not self.employee_id or self.allowed_shortage is not None:
                raise ValueError("R08 requires an employee and does not accept shortage")
        elif self.employee_id is not None or self.allowed_shortage is None:
            raise ValueError("Coverage requires a shortage limit and no employee")
        return self


class ForceRequest(StrictModel):
    requested_overrides: list[OverrideScope] = Field(default_factory=list, max_length=100)
    forced_assignments: list[Assignment] = Field(default_factory=list, max_length=100)
    authorization_reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def no_duplicate_scopes(self):
        scopes = [(x.rule_id, x.day, x.shift, x.employee_id) for x in self.requested_overrides]
        assignments = [(x.employee_id, x.day) for x in self.forced_assignments]
        if len(scopes) != len(set(scopes)) or len(assignments) != len(set(assignments)):
            raise ValueError("Duplicate scopes or multiple assignments on one employee/day")
        return self


class OverrideAuthorization(OverrideScope):
    override_id: str = Field(default_factory=lambda: f"ovr_{uuid4().hex}")
    constraint_id: str
    authorization_source: Literal["explicit_user_message", "structured_user_action"]
    source_conversation_id: str
    source_message_id: str
    client_message_id: str
    target_week: date
    base_schedule_id: str | None
    base_version: int | None
    scenario_revision: int
    employee_revision: int
    rules_fingerprint: str
    constraint_snapshot_hash: str
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    status: Literal["ACTIVE", "CONSUMED", "STALE", "REJECTED"] = "ACTIVE"
    consumed_by_schedule_id: str | None = None
