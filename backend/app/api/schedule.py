from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import Assignment, Day, ForceRequest, Schedule, ScheduleChange, Shift, Skill
from ..repository import EmployeeNotFoundError, ScheduleNotFoundError, VersionConflictError
from ..repository.schedules import ConfirmationConflictError
from ..validator.authorization import compliance_fields
from .dependencies import (
    employee_repository,
    pending_clarifications,
    schedule_repository,
    scheduling_service,
)


router = APIRouter(tags=["schedule"])


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateBody(ApiModel):
    prompt: str = ""
    week_start: date
    changes: list[ScheduleChange] = Field(default_factory=list)
    weekend_min_staff: int | None = Field(default=None, ge=0, le=30)
    max_consecutive_days: int | None = Field(default=None, ge=1, le=7)


class StaffingPreviewBody(ApiModel):
    week_start: date
    weekend_min_staff: int = Field(ge=0, le=30)
    max_consecutive_days: int | None = Field(default=None, ge=1, le=7)


@router.post("/api/schedule/staffing-preview")
def staffing_preview(body: StaffingPreviewBody) -> dict[str, Any]:
    return scheduling_service.preview_staffing(
        week_start=body.week_start, weekend_min_staff=body.weekend_min_staff,
        max_consecutive_days=body.max_consecutive_days,
    )


class ForceGenerateBody(ApiModel):
    week_start: date
    base_schedule_id: str | None
    base_version: int | None = Field(ge=1)
    force_request: ForceRequest
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = False
    source_conversation_id: str = Field(default="api", min_length=1, max_length=128)
    source_message_id: str | None = Field(default=None, max_length=128)
    client_message_id: str = Field(min_length=1, max_length=128)
    scenario_revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_base_pair(self):
        if (self.base_schedule_id is None) != (self.base_version is None):
            raise ValueError("base_schedule_id and base_version must both be provided or null")
        return self


class ReplanBody(ApiModel):
    base_schedule_id: str
    base_version: int = Field(ge=1)
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = True
    prompt: str = ""


class StoredScheduleBody(ApiModel):
    schedule_id: str
    version: int = Field(ge=1)


class ConfirmScheduleBody(StoredScheduleBody):
    schedule_id: str = Field(min_length=1, strict=True)
    version: int = Field(ge=1, strict=True)
    # Additive guard for clients carrying workbench context; identity/version
    # remain mandatory for existing integrations.
    week_start: date | None = None


class ValidateBody(ApiModel):
    schedule_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    schedule: Schedule | None = None

    @model_validator(mode="after")
    def require_source(self) -> "ValidateBody":
        if self.schedule is None and self.schedule_id is None:
            raise ValueError("schedule or schedule_id is required")
        return self


class ResolveBody(ApiModel):
    clarification_id: str
    employee_id: str


class CounterfactualBody(ApiModel):
    schedule_id: str
    employee_id: str
    day: Day
    shift: Shift
    replacement_employee_id: str | None = None


def _remember_clarification(result: dict[str, Any], operation: str, body: ApiModel) -> dict[str, Any]:
    if result.get("status") == "clarification_required":
        clarification_id = result["clarification"]["id"]
        pending_clarifications[clarification_id] = {
            "operation": operation,
            "body": body.model_dump(mode="json"),
        }
    return result


@router.post("/api/schedule/generate")
def generate_schedule(body: GenerateBody) -> dict[str, Any]:
    result = scheduling_service.generate(
        week_start=body.week_start,
        prompt=body.prompt,
        changes=body.changes,
        weekend_min_staff=body.weekend_min_staff,
        max_consecutive_days=body.max_consecutive_days,
    )
    return _remember_clarification(result, "generate", body)


@router.post("/api/schedule/force")
def force_generate_schedule(body: ForceGenerateBody) -> dict[str, Any]:
    return scheduling_service.force_generate(
        week_start=body.week_start,
        force_request=body.force_request,
        changes=body.changes,
        minimize_changes=body.minimize_changes,
        source_conversation_id=body.source_conversation_id,
        source_message_id=body.source_message_id,
        client_message_id=body.client_message_id,
        scenario_revision=body.scenario_revision,
        expected_base=(body.base_schedule_id, body.base_version),
    )


@router.post("/api/schedule/replan")
def replan_schedule(body: ReplanBody) -> dict[str, Any]:
    result = scheduling_service.replan(
        base_schedule_id=body.base_schedule_id,
        base_version=body.base_version,
        changes=body.changes,
        minimize_changes=body.minimize_changes,
        prompt=body.prompt,
    )
    return _remember_clarification(result, "replan", body)


@router.post("/api/schedule/validate")
def validate_schedule(body: ValidateBody) -> dict[str, Any]:
    if body.schedule is not None:
        validation = scheduling_service.validate(body.schedule)
        return {"status": "validated", "solver_status": None, "schedule": body.schedule.model_dump(mode="json"), "validation": validation, **compliance_fields(validation, body.schedule.status.value)}
    record = schedule_repository.get_record(body.schedule_id or "")
    if record is None or "schedule" not in record:
        raise ScheduleNotFoundError(body.schedule_id)
    if body.version is not None and record["version"] != body.version:
        raise VersionConflictError(record["version"], body.version)
    validation = scheduling_service.validate_stored(body.schedule_id or "")
    metadata = record.get("metadata", {})
    return {
        "status": "feasible",
        "schedule_id": body.schedule_id,
        "version": record["version"],
        "schedule_status": record["status"],
        "solver_status": metadata.get("solver_status", "feasible"),
        "schedule": record["schedule"].model_dump(mode="json"),
        "validation": validation,
        "diff": metadata.get("diff"),
        "impact": metadata.get("impact"),
        "metrics": metadata.get(
            "metrics",
            {"preference_rate": 0.0, "workload_gap": 0, "changed_assignments": 0},
        ),
        "explanation": metadata.get("explanation"),
        "rule_config": metadata.get("rule_config"),
        **compliance_fields(validation, record["status"]),
    }


@router.post("/api/schedule/confirm")
def confirm_schedule(body: ConfirmScheduleBody) -> dict[str, Any]:
    if body.week_start is not None:
        record = schedule_repository.get_record(body.schedule_id)
        if record is None or "schedule" not in record:
            raise ScheduleNotFoundError(body.schedule_id)
        if record["schedule"].week_start != body.week_start:
            raise ConfirmationConflictError(
                "draft_week_mismatch", "该草稿不属于当前周，请刷新后重新确认。",
                {"expected_week": body.week_start.isoformat(), "draft_week": record["week_start"]},
            )
    return scheduling_service.confirm(body.schedule_id, body.version)


@router.post("/api/schedule/cancel")
def cancel_schedule(body: StoredScheduleBody) -> dict[str, Any]:
    return scheduling_service.cancel(body.schedule_id, body.version)


@router.post("/api/schedule/resolve")
def resolve_entity(body: ResolveBody) -> dict[str, Any]:
    pending = pending_clarifications.pop(body.clarification_id, None)
    if pending is None:
        raise ScheduleNotFoundError(body.clarification_id)
    try:
        employee = scheduling_service.intent_parser.resolver.validate_selected(
            body.employee_id, employee_repository.list()
        )
    except LookupError as exc:
        raise EmployeeNotFoundError(body.employee_id) from exc
    prompt = pending["body"].get("prompt", "")
    day = scheduling_service.intent_parser.extract_day(prompt)
    if day is None:
        raise ValueError("The pending request does not contain a resolvable day")
    change = ScheduleChange(employee_id=employee.id, type="leave", day=day)
    if pending["operation"] == "generate":
        return scheduling_service.generate(
            week_start=date.fromisoformat(pending["body"]["week_start"]),
            prompt="",
            changes=[change],
            weekend_min_staff=pending["body"].get("weekend_min_staff"),
            max_consecutive_days=pending["body"].get("max_consecutive_days"),
        )
    return scheduling_service.replan(
        base_schedule_id=pending["body"]["base_schedule_id"],
        base_version=pending["body"]["base_version"],
        changes=[change],
        minimize_changes=bool(pending["body"].get("minimize_changes", True)),
    )


@router.post("/api/schedule/explain")
def explain_counterfactual(body: CounterfactualBody) -> dict[str, Any]:
    record = schedule_repository.get_record(body.schedule_id)
    if record is None or "schedule" not in record:
        raise ScheduleNotFoundError(body.schedule_id)
    schedule: Schedule = record["schedule"]
    employees = {employee.id: employee for employee in employee_repository.list()}
    if body.employee_id not in employees:
        raise ValueError(f"Employee {body.employee_id} does not exist")
    target = (body.employee_id, body.day, body.shift)
    keys = {(item.employee_id, item.day, item.shift) for item in schedule.assignments}
    if target not in keys:
        raise ValueError("The employee is not assigned to the selected shift")

    remaining = [
        item
        for item in schedule.assignments
        if (item.employee_id, item.day, item.shift) != target
    ]
    if body.replacement_employee_id:
        replacement = employees.get(body.replacement_employee_id)
        if replacement is None:
            raise ValueError(f"Employee {body.replacement_employee_id} does not exist")
        remaining.append(
            Assignment(
                employee_id=replacement.id,
                day=body.day,
                shift=body.shift,
            )
        )
    candidate = schedule.model_copy(update={"assignments": remaining})
    changes = [
        ScheduleChange.model_validate(item)
        for item in record.get("metadata", {}).get("requested_changes", [])
    ]
    base = (
        schedule_repository.get(record["base_schedule_id"])
        if record.get("base_schedule_id")
        else None
    )
    context = scheduling_service.context_builder.build(
        schedule.week_start,
        base_schedule=base,
        changes=changes,
        minimize_changes=bool(base),
        allow_history_bootstrap=False,
        rule_config=record.get("metadata", {}).get("rule_config"),
    )
    validation = scheduling_service.validate(candidate, context=context)
    failures = [
        check
        for check in validation["checks"]
        if not check["passed"]
    ]

    slot_before = [
        employees[item.employee_id]
        for item in schedule.assignments
        if item.day == body.day and item.shift == body.shift and item.employee_id in employees
    ]
    coverage_before = {
        "manager": sum(Skill.MANAGER in employee.skills for employee in slot_before),
        "beverage": sum(Skill.BEVERAGE in employee.skills for employee in slot_before),
        "cashier": sum(Skill.CASHIER in employee.skills for employee in slot_before),
        "staff": len(slot_before),
    }
    coverage_after = dict(coverage_before)
    removed = employees[body.employee_id]
    coverage_after["staff"] -= 1
    for skill in (Skill.MANAGER, Skill.BEVERAGE, Skill.CASHIER):
        if skill in removed.skills:
            coverage_after[skill.value] -= 1
    if body.replacement_employee_id:
        added = employees[body.replacement_employee_id]
        coverage_after["staff"] += 1
        for skill in (Skill.MANAGER, Skill.BEVERAGE, Skill.CASHIER):
            if skill in added.skills:
                coverage_after[skill.value] += 1

    necessary_rules = [check["rule_id"] for check in failures]
    if body.replacement_employee_id:
        summary = (
            f"Replacing {body.employee_id} with {body.replacement_employee_id} "
            + ("keeps all checked hard constraints valid." if not failures else f"would violate {', '.join(necessary_rules)}.")
        )
    else:
        summary = (
            f"{body.employee_id} is necessary for {', '.join(necessary_rules)} in this shift."
            if failures
            else f"Removing {body.employee_id} leaves the selected hard constraints valid."
        )
    return {
        "status": "explained",
        "schedule_id": body.schedule_id,
        "employee_id": body.employee_id,
        "replacement_employee_id": body.replacement_employee_id,
        "day": body.day.value,
        "shift": body.shift.value,
        "coverage_before": coverage_before,
        "coverage_after": coverage_after,
        "necessary_rules": necessary_rules,
        "validation": validation,
        "summary": summary,
    }


@router.get("/api/schedules/latest")
def latest_schedule(
    status: Literal["draft", "confirmed"] = "confirmed",
    week_start: date | None = None,
) -> dict[str, Any] | None:
    schedule = schedule_repository.latest(status=status, week_start=week_start)
    return schedule.model_dump(mode="json") if schedule else None


def _schedule_payload(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    schedule: Schedule = record["schedule"]
    return schedule.model_dump(mode="json")


def _result_payload(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    schedule: Schedule = record["schedule"]
    metadata = record.get("metadata", {})
    return {
        "status": "feasible" if record["status"] == "draft" else "confirmed",
        "schedule_id": record["schedule_id"],
        "version": record["version"],
        "schedule_status": record["status"],
        "solver_status": metadata.get("solver_status", "feasible"),
        "schedule": schedule.model_dump(mode="json"),
        "validation": record.get("validation", {}),
        "diff": metadata.get("diff"),
        "impact": metadata.get("impact"),
        "metrics": metadata.get(
            "metrics",
            {"preference_rate": 0.0, "workload_gap": 0, "changed_assignments": 0},
        ),
        "explanation": metadata.get("explanation"),
        "rule_config": metadata.get("rule_config"),
        **compliance_fields(record.get("validation", {}), record["status"]),
    }


@router.get("/api/schedules/week-context")
def schedule_week_context(week_start: date) -> dict[str, Any]:
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    confirmed, draft = schedule_repository.current_records_for_week(week_start)
    display = draft or confirmed
    versions = schedule_repository.versions_for_week(week_start)
    return {
        "week_start": week_start.isoformat(),
        "confirmed_schedule": _schedule_payload(confirmed),
        "draft_schedule": _schedule_payload(draft),
        "display_schedule": _schedule_payload(display),
        "versions": [
            {
                "schedule_id": item["schedule_id"],
                "version": item["version"],
                "status": item["status"],
                "created_at": item["created_at"],
                "parent_schedule_id": item["parent_schedule_id"],
                "base_schedule_id": item["base_schedule_id"],
                "base_version": item["base_version"],
                "compliance_status": item.get("compliance_status", "compliant" if item.get("validation", {}).get("passed") else "invalid"),
                "authorized_violation_count": len(item.get("validation", {}).get("authorized_violations", [])),
                "violations": item.get("validation", {}).get("violations", []),
            }
            for item in versions
        ],
        "result": _result_payload(display),
    }


@router.get("/api/schedules/weeks")
def schedule_weeks(
    anchor_week_start: date,
    radius: int = Query(default=6, ge=0, le=26),
) -> dict[str, Any]:
    if anchor_week_start.weekday() != 0:
        raise ValueError("anchor_week_start must be a Monday")
    weeks = []
    for offset in range(-radius, radius + 1):
        week = anchor_week_start + timedelta(days=offset * 7)
        confirmed, draft = schedule_repository.current_records_for_week(week)
        display = draft or confirmed
        weeks.append(
            {
                "week_start": week.isoformat(),
                "schedule_id": display["schedule_id"] if display else None,
                "version": display["version"] if display else None,
                "status": display["status"] if display else "not_generated",
            }
        )
    return {"weeks": weeks}


@router.get("/api/schedules/{schedule_id}")
def get_schedule(schedule_id: str) -> dict[str, Any]:
    record = schedule_repository.get_record(schedule_id)
    if record is None or "schedule" not in record:
        raise ScheduleNotFoundError(schedule_id)
    return record["schedule"].model_dump(mode="json")


@router.get("/api/schedules/{schedule_id}/versions")
def schedule_versions(schedule_id: str) -> dict[str, Any]:
    versions = schedule_repository.versions(schedule_id)
    return {
        "versions": [
            {
                "schedule_id": item["schedule_id"],
                "version": item["version"],
                "status": item["status"],
                "created_at": item["created_at"],
                "parent_schedule_id": item["parent_schedule_id"],
                "base_schedule_id": item["base_schedule_id"],
                "base_version": item["base_version"],
                "compliance_status": item.get("compliance_status", "compliant" if item.get("validation", {}).get("passed") else "invalid"),
                "authorized_violation_count": len(item.get("validation", {}).get("authorized_violations", [])),
                "violations": item.get("validation", {}).get("violations", []),
            }
            for item in versions
        ]
    }
