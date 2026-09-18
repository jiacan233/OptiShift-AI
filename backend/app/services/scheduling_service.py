from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable
from uuid import uuid4

from ..models import (
    RequestIntent,
    Schedule,
    ScheduleChange,
    SolverStatus,
)
from ..repository import (
    EmployeeRepository,
    InvalidScheduleStateError,
    ScheduleNotFoundError,
    ScheduleRepository,
)
from ..solver.primary_solver import PrimarySolver
from ..validator import RuleValidator
from .context_builder import ContextBuilder
from .diff_service import build_diff
from .explanation import ExplanationService, normalize_validation
from .intent_parser import IntentParser
from .request_validator import validate_changes
from .rules import load_rule_config


logger = logging.getLogger("optishift.scheduling")


class SolverOutputError(RuntimeError):
    pass


class SchedulingService:
    def __init__(
        self,
        employees: EmployeeRepository,
        schedules: ScheduleRepository,
        *,
        solver: PrimarySolver | None = None,
        validator: RuleValidator | None = None,
    ) -> None:
        self.employees = employees
        self.schedules = schedules
        self.context_builder = ContextBuilder(employees, schedules, load_rule_config())
        self.solver = solver or PrimarySolver()
        self.validator = validator or RuleValidator()
        self.intent_parser = IntentParser()
        self.explanations = ExplanationService()

    @staticmethod
    def _new_schedule_id() -> str:
        return f"sch_{uuid4().hex[:12]}"

    @staticmethod
    def _infeasible_response(result: Any) -> dict[str, Any]:
        diagnosis = result.diagnosis
        if diagnosis is None:
            return {
                "status": "infeasible",
                "conflicts": [],
                "blocking_candidates": [],
                "diagnosis": None,
                "message": result.message or "No valid schedule exists.",
                "generated_valid_schedule": False,
            }
        raw = diagnosis.model_dump(mode="json")
        logger.info(
            "schedule_infeasible solver_status=%s diagnosis_level=3 conflicts=%s",
            result.status.value,
            len(raw.get("capacity_conflicts", [])) + len(raw.get("diagnostic_conflicts", [])),
        )
        conflicts: list[dict[str, Any]] = []
        for conflict in raw.get("capacity_conflicts", []):
            conflicts.append(conflict)
        for conflict in raw.get("diagnostic_conflicts", []):
            normalized = dict(conflict)
            normalized["available"] = normalized.pop("actual", 0)
            if not any(
                existing.get("rule_id") == normalized.get("rule_id")
                and existing.get("day") == normalized.get("day")
                and existing.get("shift") == normalized.get("shift")
                for existing in conflicts
            ):
                conflicts.append(normalized)
        return {
            "status": "infeasible",
            "conflicts": conflicts,
            "blocking_candidates": raw.get("blocking_candidates", []),
            "diagnosis": raw,
            "message": raw.get("summary") or result.message or "No valid schedule exists.",
            "generated_valid_schedule": False,
        }

    def _complete_draft(
        self,
        *,
        context: Any,
        result: Any,
        lineage_id: str,
        base_schedule: Schedule | None,
        base_version: int | None,
        employee_revision: int,
        metadata_extra: dict[str, Any] | None = None,
        before_commit: Callable[[], None] | None = None,
        agent_turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        if result.status is SolverStatus.INFEASIBLE:
            return self._infeasible_response(result)
        if result.status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            return {
                "status": "solver_unknown",
                "solver_status": result.status.value,
                "message": result.message or "The solver did not return a usable schedule.",
            }
        if result.schedule is None:
            raise SolverOutputError("Solver reported success without a schedule")

        validation_result = self.validator.validate(
            result.schedule, context.employees, context=context, rules=context.rules
        )
        validation = normalize_validation(validation_result)
        if not validation["passed"]:
            logger.error(
                "solver_validation_failed",
                extra={
                    "schedule_id": result.schedule.schedule_id,
                    "version": result.schedule.version,
                },
            )
            raise SolverOutputError("Independent validation rejected solver output")

        diff, impact = build_diff(
            base_schedule, result.schedule, context.requested_changes
        )
        metrics = dict(result.metrics)
        metrics["changed_assignments"] = metrics.get(
            "change_count", len(diff["added"]) + len(diff["removed"])
        )
        metrics["changed_shifts"] = diff["changed_shifts"]
        metrics["affected_employees"] = len(diff["affected_employees"])
        metrics["hard_violations"] = 0
        explanation = self.explanations.build(
            result.schedule, context.employees, validation, metrics
        )
        metadata = {
            **dict(metadata_extra or {}),
            "solver_status": result.status.value,
            "metrics": metrics,
            "diff": diff,
            "impact": impact,
            "explanation": explanation,
            "requested_changes": [
                change.model_dump(mode="json") for change in context.requested_changes
            ],
            "history_status": context.history_status.value,
            "history_schedule_id": context.history_schedule_id,
            "history_schedule_version": context.history_schedule_version,
            "employee_revision": employee_revision,
        }
        if before_commit is not None:
            before_commit()
        self.schedules.save_draft(
            result.schedule,
            lineage_id=lineage_id,
            base_schedule_id=base_schedule.schedule_id if base_schedule else None,
            base_version=base_version,
            validation=validation,
            metadata=metadata,
            employee_revision=employee_revision,
            agent_turn_guard=agent_turn_guard,
        )
        logger.info(
            "schedule_draft_created",
            extra={
                "schedule_id": result.schedule.schedule_id,
                "version": result.schedule.version,
                "solver_status": result.status.value,
                "validation_passed": True,
                "solve_duration": metrics.get("solve_duration_seconds"),
            },
        )
        return {
            "status": "feasible",
            "solver_status": result.status.value,
            "schedule_id": result.schedule.schedule_id,
            "version": result.schedule.version,
            "schedule_status": "draft",
            "schedule": result.schedule.model_dump(mode="json"),
            "validation": validation,
            "diff": diff,
            "impact": impact,
            "metrics": metrics,
            "explanation": explanation,
        }

    def generate(
        self,
        *,
        week_start: date,
        prompt: str = "",
        changes: list[ScheduleChange] | None = None,
        metadata_extra: dict[str, Any] | None = None,
        before_commit: Callable[[], None] | None = None,
        agent_turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        if week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        employee_list, employee_revision = self.employees.list_with_revision()
        effective_changes = list(changes or [])
        minimize_changes = False
        if prompt:
            parsed = self.intent_parser.parse(
                prompt, employee_list, default_intent=RequestIntent.GENERATE
            )
            if parsed.resolution and parsed.resolution.get("status") != "resolved":
                return self._clarification_response(prompt, parsed.resolution)
            if not effective_changes:
                effective_changes = parsed.changes
            minimize_changes = parsed.minimize_changes
        validate_changes(effective_changes, employee_list)
        base_record = self.schedules.current_confirmed_record_for_week(week_start)
        base_schedule: Schedule | None = (
            base_record["schedule"] if base_record is not None else None
        )
        base_version = base_schedule.version if base_schedule is not None else None
        context = self.context_builder.build(
            week_start,
            base_schedule=base_schedule,
            changes=effective_changes,
            minimize_changes=minimize_changes,
            employees=employee_list,
            allow_history_bootstrap=True,
        )
        schedule_id = self._new_schedule_id()
        result = self.solver.solve(
            context,
            week_start=week_start,
            schedule_id=schedule_id,
            version=(base_version + 1 if base_version is not None else 1),
            parent_schedule_id=(base_schedule.schedule_id if base_schedule else None),
        )
        return self._complete_draft(
            context=context,
            result=result,
            lineage_id=(base_record["lineage_id"] if base_record else schedule_id),
            base_schedule=base_schedule,
            base_version=base_version,
            employee_revision=employee_revision,
            metadata_extra=metadata_extra,
            before_commit=before_commit,
            agent_turn_guard=agent_turn_guard,
        )

    def replan(
        self,
        *,
        base_schedule_id: str,
        base_version: int,
        changes: list[ScheduleChange],
        minimize_changes: bool = True,
        prompt: str = "",
        metadata_extra: dict[str, Any] | None = None,
        before_commit: Callable[[], None] | None = None,
        agent_turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        base_record = self.schedules.assert_current_base(base_schedule_id, base_version)
        base_schedule: Schedule = base_record["schedule"]
        employee_list, employee_revision = self.employees.list_with_revision()
        effective_changes = list(changes)
        if prompt and not effective_changes:
            parsed = self.intent_parser.parse(
                prompt, employee_list, default_intent=RequestIntent.REPLAN
            )
            if parsed.resolution and parsed.resolution.get("status") != "resolved":
                return self._clarification_response(prompt, parsed.resolution)
            effective_changes = parsed.changes
            minimize_changes = minimize_changes or parsed.minimize_changes
        validate_changes(effective_changes, employee_list)
        context = self.context_builder.build(
            base_schedule.week_start,
            base_schedule=base_schedule,
            changes=effective_changes,
            minimize_changes=minimize_changes,
            employees=employee_list,
            allow_history_bootstrap=False,
        )
        schedule_id = self._new_schedule_id()
        result = self.solver.solve(
            context,
            week_start=base_schedule.week_start,
            schedule_id=schedule_id,
            version=base_version + 1,
            parent_schedule_id=base_schedule.schedule_id,
        )
        return self._complete_draft(
            context=context,
            result=result,
            lineage_id=base_record["lineage_id"],
            base_schedule=base_schedule,
            base_version=base_version,
            employee_revision=employee_revision,
            metadata_extra=metadata_extra,
            before_commit=before_commit,
            agent_turn_guard=agent_turn_guard,
        )

    @staticmethod
    def _clarification_response(prompt: str, resolution: dict[str, Any]) -> dict[str, Any]:
        if resolution.get("status") == "entity_not_found":
            return {
                "status": "entity_not_found",
                "message": "No employee in master data matches the request.",
                "details": resolution,
            }
        return {
            "status": "clarification_required",
            "clarification": {
                "id": f"clar_{uuid4().hex[:10]}",
                "prompt": prompt,
                "candidates": resolution.get("candidates", []),
            },
        }

    def validate(self, schedule: Schedule, *, context: Any | None = None) -> dict[str, Any]:
        if context is None:
            employees, _employee_revision = self.employees.list_with_revision()
            context = self.context_builder.build(
                schedule.week_start,
                employees=employees,
                allow_history_bootstrap=False,
                allow_ephemeral_known_empty=True,
            )
        else:
            employees = context.employees
        result = self.validator.validate(schedule, employees, context=context)
        return normalize_validation(result)

    def validate_stored(
        self, schedule_id: str, *, enforce_employee_revision: bool = False
    ) -> dict[str, Any]:
        record = self.schedules.get_record(schedule_id)
        if record is None or "schedule" not in record:
            raise ScheduleNotFoundError(schedule_id)
        schedule: Schedule = record["schedule"]
        employee_list, employee_revision = self.employees.list_with_revision()
        stored_revision = record["metadata"].get("employee_revision")
        if (
            enforce_employee_revision
            and stored_revision is not None
            and stored_revision != employee_revision
        ):
            raise InvalidScheduleStateError(
                "Employee master data changed after this draft was created"
            )
        changes = [ScheduleChange.model_validate(item) for item in record["metadata"].get("requested_changes", [])]
        base = (
            self.schedules.get(record["base_schedule_id"])
            if record["base_schedule_id"]
            else None
        )
        context = self.context_builder.build(
            schedule.week_start,
            base_schedule=base,
            changes=changes,
            minimize_changes=bool(base),
            employees=employee_list,
            allow_history_bootstrap=False,
        )
        return self.validate(schedule, context=context)

    def confirm(self, schedule_id: str, version: int) -> dict[str, Any]:
        validation = self.validate_stored(
            schedule_id,
            enforce_employee_revision=True,
        )
        if not validation["passed"]:
            raise SolverOutputError("Draft is no longer valid against current employee data")
        confirmed = self.schedules.confirm(schedule_id, version)
        record = self.schedules.get_record(schedule_id) or {}
        metadata = record.get("metadata", {})
        return {
            "status": "confirmed",
            "schedule_id": confirmed.schedule_id,
            "version": confirmed.version,
            "schedule_status": "confirmed",
            "schedule": confirmed.model_dump(mode="json"),
            "validation": validation,
            "diff": metadata.get("diff"),
            "impact": metadata.get("impact"),
            "metrics": metadata.get("metrics", {}),
            "explanation": metadata.get("explanation"),
        }

    def cancel(self, schedule_id: str, version: int) -> dict[str, Any]:
        cancelled = self.schedules.cancel(schedule_id, version)
        current = None
        base_schedule_id = cancelled.get("base_schedule_id")
        if base_schedule_id:
            current_schedule = self.schedules.get(base_schedule_id)
            current = current_schedule.model_dump(mode="json") if current_schedule else None
        return {**cancelled, "confirmed_schedule": current}
