from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from ..models import (
    Assignment,
    PatchOperation,
    RequestIntent,
    ScenarioPatch,
    Schedule,
    ScheduleChange,
    ScheduleStatus,
    SolverStatus,
    ForceRequest,
    OverrideAuthorization,
)
from ..repository import (
    EmployeeRepository,
    InvalidScheduleStateError,
    ScheduleNotFoundError,
    ScheduleRepository,
    VersionConflictError,
)
from ..repository.scenarios import ScenarioRepository
from ..solver.primary_solver import PrimarySolver
from ..validator import RuleValidator
from ..validator.authorization import (
    authorization_is_active,
    classify_validation,
    compliance_fields,
    constraint_id,
    context_snapshot,
    fingerprint,
)
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
        scenarios: ScenarioRepository | None = None,
    ) -> None:
        self.employees = employees
        self.schedules = schedules
        self.context_builder = ContextBuilder(employees, schedules, load_rule_config())
        self.solver = solver or PrimarySolver()
        self.validator = validator or RuleValidator()
        self.scenarios = scenarios or ScenarioRepository(schedules.database)
        self.intent_parser = IntentParser()
        self.explanations = ExplanationService()

    @staticmethod
    def _new_schedule_id() -> str:
        return f"sch_{uuid4().hex[:12]}"

    @staticmethod
    def _infeasible_response(result: Any) -> dict[str, Any]:
        diagnosis = result.diagnosis
        has_solver_status = hasattr(result, "status")
        solver_status = getattr(getattr(result, "status", None), "value", "infeasible")
        if diagnosis is None:
            response = {
                "status": "infeasible",
                "conflicts": [],
                "blocking_candidates": [],
                "diagnosis": None,
                "message": result.message or "No valid schedule exists.",
                "generated_valid_schedule": False,
            }
            if has_solver_status:
                response.update({"solver_status": solver_status, "can_confirm": False})
                response.update(compliance_fields({"passed": False}))
                response.update(validation=None)
            return response
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
        response = {
            "status": "infeasible",
            "conflicts": conflicts,
            "blocking_candidates": raw.get("blocking_candidates", []),
            "diagnosis": raw,
            "message": raw.get("summary") or result.message or "No valid schedule exists.",
            "generated_valid_schedule": False,
            "preview_schedule": raw.get("preview_schedule"),
            "coverage_gaps": raw.get("coverage_gaps", []),
            "strict_feasible": False,
            "minimum_shortage": raw.get("minimum_shortage", 0),
        }
        if has_solver_status:
            response.update({"solver_status": solver_status, "can_confirm": False})
        response.update(compliance_fields({"passed": False}))
        response.update(validation=None)
        return response

    @staticmethod
    def _stored_response(record: dict[str, Any]) -> dict[str, Any]:
        schedule: Schedule = record["schedule"]
        metadata = record.get("metadata", {})
        validation = record.get("validation", {})
        return {
            "status": "confirmed" if record["status"] == "confirmed" else "feasible",
            "solver_status": metadata.get("solver_status", "feasible"),
            "schedule_id": schedule.schedule_id,
            "version": schedule.version,
            "schedule_status": record["status"],
            "schedule": schedule.model_dump(mode="json"),
            "validation": validation,
            "diff": metadata.get("diff"),
            "impact": metadata.get("impact"),
            "metrics": metadata.get("metrics", {}),
            "explanation": metadata.get("explanation"),
            "rule_config": metadata.get("rule_config"),
            **compliance_fields(validation, record["status"]),
        }

    def preview_staffing(self, *, week_start: date, weekend_min_staff: int, max_consecutive_days: int | None = None) -> dict[str, Any]:
        """Solve a staffing experiment without saving schedules or history boundaries."""
        if week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        employees = self.employees.list()
        base = self.schedules.current_confirmed_record_for_week(week_start)
        context = self.context_builder.build(
            week_start, employees=employees, base_schedule=base["schedule"] if base else None,
            allow_history_bootstrap=False, allow_ephemeral_known_empty=True,
        )
        context = context.model_copy(update={
            "rules": context.rules.model_copy(update={
                **({"weekend_min_staff": weekend_min_staff} if weekend_min_staff is not None else {}),
                **({"max_consecutive_days": max_consecutive_days} if max_consecutive_days is not None else {}),
            })
        })
        result = self.solver.solve(context, week_start=week_start)
        response: dict[str, Any] = {
            "status": result.status.value, "target_week": week_start.isoformat(),
            "weekend_min_staff": weekend_min_staff, "can_confirm": False,
            "strict_feasible": False, "conflicts": [], "metrics": dict(result.metrics),
        }
        if result.schedule is not None and result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            validation = normalize_validation(self.validator.validate(result.schedule, employees, context=context))
            response.update(strict_feasible=validation["passed"], validation=validation,
                            preview_schedule=result.schedule.model_dump(mode="json"))
        elif result.status is SolverStatus.INFEASIBLE:
            response.update(self._infeasible_response(result))
        return response

    def preview_scenario(
        self,
        *,
        week_start: date,
        patches: list[ScenarioPatch],
        base_schedule: Schedule | None = None,
    ) -> dict[str, Any]:
        employee_list, _ = self.employees.list_with_revision()
        changes: list[ScheduleChange] = []
        for patch in patches:
            if patch.operation is PatchOperation.CLEAR:
                continue
            for day in patch.days:
                changes.append(ScheduleChange(employee_id=patch.employee_id, type=patch.change_type, day=day))
        validate_changes(changes, employee_list)
        context = self.context_builder.build(
            week_start,
            base_schedule=base_schedule,
            changes=changes,
            minimize_changes=True,
            employees=employee_list,
            allow_history_bootstrap=True,
        )
        result = self.solver.solve(context, week_start=week_start, version=1)
        if result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE} and result.schedule is not None:
            validation = normalize_validation(self.validator.validate(result.schedule, employee_list, context=context))
            return {
                "status": "scenario_preview",
                "solver_status": result.status.value,
                "strict_feasible": True,
                "target_week": week_start.isoformat(),
                "schedule": result.schedule.model_dump(mode="json"),
                "preview_schedule": result.schedule.model_dump(mode="json"),
                "validation": validation,
                "metrics": dict(result.metrics),
                "coverage_gaps": [],
                "conflicts": [],
                "suggestions": [],
                "can_confirm": False,
            }
        infeasible = self._infeasible_response(result)
        suggestions: list[dict[str, Any]] = []
        # Verify a small deterministic set of repairs. A suggestion is never
        # emitted from prose alone: each candidate is solved with the same
        # strict model before it is returned.
        for patch_index, patch in enumerate(patches):
            if patch.change_type.value not in {"leave", "unavailable"} or not patch.days:
                continue
            for day in patch.days[:2]:
                candidate_patches = [
                    item.model_copy(
                        update={"days": [value for value in item.days if value != day]}
                    )
                    for item in patches
                ]
                candidate_patches = [item for item in candidate_patches if item.days]
                candidate_changes = [
                    ScheduleChange(employee_id=item.employee_id, type=item.change_type, day=value)
                    for item in candidate_patches
                    for value in item.days
                ]
                candidate_context = self.context_builder.build(
                    week_start,
                    base_schedule=base_schedule,
                    changes=candidate_changes,
                    minimize_changes=True,
                    employees=employee_list,
                    allow_history_bootstrap=True,
                )
                candidate_result = self.solver.solve(candidate_context, week_start=week_start, version=1)
                if candidate_result.status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
                    continue
                suggestions.append({
                    "id": f"repair_{patch_index + 1}_{day.value.lower()}",
                    "suggestion_id": f"repair_{patch_index + 1}_{day.value.lower()}",
                    "title": f"恢复 {patch.employee_id} {day.value} 可用",
                    "description": f"移除 {patch.employee_id} 在 {day.value} 的临时限制后，严格 Solver 已验证可以生成完整排班。",
                    "scenario_patch": {
                        "employee_id": patch.employee_id,
                        "operation": "remove",
                        "days": [day.value],
                        "change_type": patch.change_type.value,
                    },
                    "validation_result": {"status": "feasible", "strict_feasible": True},
                })
                if len(suggestions) >= 4:
                    break
            if len(suggestions) >= 4:
                break
        return {
            **infeasible,
            "status": "scenario_preview",
            "strict_feasible": False,
            "target_week": week_start.isoformat(),
            "can_confirm": False,
            "suggestions": suggestions,
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
        authorizations: list[OverrideAuthorization] | None = None,
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
        validation = classify_validation(
            normalize_validation(validation_result), result.schedule.week_start, authorizations
        )
        if not validation["confirmable"]:
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
        metrics["hard_violations"] = len(validation.get("violations", []))
        explanation = self.explanations.build(
            result.schedule, context.employees, validation, metrics
        )
        metadata = {
            **dict(metadata_extra or {}),
            "solver_status": result.status.value,
            "rule_config": context.rules.model_dump(mode="json"),
            "source_rules_fingerprint": fingerprint(self.context_builder.rules.model_dump(mode="json")),
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
            "compliance_status": validation["compliance_status"],
        }
        if authorizations:
            metadata["override_authorizations"] = [
                item.model_copy(
                    update={
                        "status": "CONSUMED",
                        "consumed_by_schedule_id": result.schedule.schedule_id,
                    }
                ).model_dump(mode="json")
                for item in authorizations
            ]
        if before_commit is not None:
            before_commit()
        saved = self.schedules.save_draft(
            result.schedule,
            lineage_id=lineage_id,
            base_schedule_id=base_schedule.schedule_id if base_schedule else None,
            base_version=base_version,
            validation=validation,
            metadata=metadata,
            employee_revision=employee_revision,
            agent_turn_guard=agent_turn_guard,
        )
        if saved.schedule_id != result.schedule.schedule_id:
            return self._stored_response({**self.schedules.get_record(saved.schedule_id), "schedule": saved})
        logger.info(
            "schedule_draft_created",
            extra={
                "schedule_id": result.schedule.schedule_id,
                "version": result.schedule.version,
                "solver_status": result.status.value,
                "validation_passed": validation["passed"],
                "authorized_violation_count": len(validation.get("authorized_violations", [])),
                "unauthorized_violation_count": len(validation.get("unauthorized_violations", [])),
                "protected_violation_count": len(validation.get("protected_violations", [])),
                "compliance_status": validation["compliance_status"],
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
            "rule_config": context.rules.model_dump(mode="json"),
            **compliance_fields(validation, "draft"),
        }

    def generate(
        self,
        *,
        week_start: date,
        prompt: str = "",
        weekend_min_staff: int | None = None,
        max_consecutive_days: int | None = None,
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
        if max_consecutive_days is not None and not 1 <= max_consecutive_days <= 7:
            raise ValueError("max_consecutive_days must be between 1 and 7")
        if weekend_min_staff is not None or max_consecutive_days is not None:
            if weekend_min_staff is not None and not 0 <= weekend_min_staff <= 30:
                raise ValueError("weekend_min_staff must be between 0 and 30")
            context = context.model_copy(update={
                "rules": context.rules.model_copy(update={
                    **({"weekend_min_staff": weekend_min_staff} if weekend_min_staff is not None else {}),
                    **({"max_consecutive_days": max_consecutive_days} if max_consecutive_days is not None else {}),
                })
            })
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

    def force_generate(
        self,
        *,
        week_start: date,
        force_request: ForceRequest,
        changes: list[ScheduleChange] | None = None,
        minimize_changes: bool = False,
        source_conversation_id: str = "api",
        source_message_id: str | None = None,
        client_message_id: str | None = None,
        scenario_revision: int = 0,
        expected_base: tuple[str | None, int | None] | None = None,
        metadata_extra: dict[str, Any] | None = None,
        before_commit: Callable[[], None] | None = None,
        agent_turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        """Generate with exact, request-scoped exceptions after a strict attempt.

        This deliberately accepts only a structured ForceRequest. Text routing may
        identify a request, but cannot manufacture its scope or authorization.
        """
        if week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        if any(item.type.value in {"available", "assign", "unassign"} for item in (changes or [])):
            raise ValueError("Force cannot change availability or ordinary assignments; use exact forced_assignments")
        if client_message_id:
            existing = self.schedules.find_force_schedule_for_request(
                week_start,
                conversation_id=source_conversation_id,
                client_message_id=client_message_id,
            )
            if existing is not None:
                return self._stored_response(existing)
        employee_list, employee_revision = self.employees.list_with_revision()
        effective_changes = list(changes or [])
        validate_changes(effective_changes, employee_list)
        base_record = self.schedules.current_confirmed_record_for_week(week_start)
        base_schedule = base_record["schedule"] if base_record else None
        base_version = base_schedule.version if base_schedule else None
        version = (base_version + 1) if base_version is not None else 1
        parent_schedule_id = base_schedule.schedule_id if base_schedule else None

        if expected_base is not None and expected_base != (parent_schedule_id, base_version):
            raise VersionConflictError(base_version, expected_base[1])

        # Force input is structured but still comes from an untrusted client.
        # The context validator below also protects the solver from impossible
        # employee references before model variables are constructed.
        known_employee_ids = {employee.id for employee in employee_list}
        unknown_forced = sorted(
            {item.employee_id for item in force_request.forced_assignments}
            - known_employee_ids
        )
        unknown_override = sorted(
            {item.employee_id for item in force_request.requested_overrides if item.employee_id}
            - known_employee_ids
        )
        if unknown_forced or unknown_override:
            logger.info("override_rejected", extra={"reason": "unknown_employee"})
            raise ValueError("Force requests must reference existing employees")

        strict_context = self.context_builder.build(
            week_start,
            base_schedule=base_schedule,
            changes=effective_changes,
            minimize_changes=minimize_changes,
            employees=employee_list,
            allow_history_bootstrap=True,
            user_forced_assignments=force_request.forced_assignments,
        )
        strict_result = self.solver.solve(
            strict_context,
            week_start=week_start,
            schedule_id=self._new_schedule_id(),
            version=version,
            parent_schedule_id=parent_schedule_id,
        )
        if strict_result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            return self._complete_draft(
                context=strict_context,
                result=strict_result,
                lineage_id=base_record["lineage_id"] if base_record else strict_result.schedule.schedule_id,
                base_schedule=base_schedule,
                base_version=base_version,
                employee_revision=employee_revision,
                metadata_extra={
                    **dict(metadata_extra or {}),
                    "force_requested": True,
                    "force_not_needed": True,
                    "scenario_revision": scenario_revision,
                    "force_source_conversation_id": source_conversation_id,
                    "force_source_message_id": source_message_id or client_message_id,
                    "force_client_message_id": client_message_id,
                    "user_forced_assignments": [
                        item.model_dump(mode="json") for item in force_request.forced_assignments
                    ],
                },
                before_commit=before_commit,
                agent_turn_guard=agent_turn_guard,
            )
        if strict_result.status is not SolverStatus.INFEASIBLE:
            return {**self._infeasible_response(strict_result), "status": "solver_unknown"}
        if not force_request.requested_overrides:
            response = self._infeasible_response(strict_result)
            response.update({
                "status": "clarification_required",
                "clarification": {
                    "id": f"clar_{uuid4().hex[:10]}",
                    "prompt": "严格排班不可行。请明确授权的规则、日期和班次；覆盖规则还需要缺口上限，请假例外还需要员工编号。",
                    "candidates": [],
                },
            })
            return response

        snapshot_hash = fingerprint(context_snapshot(strict_context, week_start))
        rules_fingerprint = fingerprint(strict_context.rules.model_dump(mode="json"))
        created = datetime.now(timezone.utc)
        message_id = source_message_id or client_message_id or f"msg_{uuid4().hex[:12]}"
        idempotency_key = client_message_id or message_id
        authorizations = [
            OverrideAuthorization(
                **scope.model_dump(),
                constraint_id=constraint_id(
                    week_start.isoformat(), scope.rule_id, scope.day.value, scope.shift.value, scope.employee_id
                ),
                authorization_source="structured_user_action" if source_conversation_id == "api" else "explicit_user_message",
                source_conversation_id=source_conversation_id,
                source_message_id=message_id,
                client_message_id=idempotency_key,
                target_week=week_start,
                base_schedule_id=base_schedule.schedule_id if base_schedule else None,
                base_version=base_version,
                scenario_revision=scenario_revision,
                employee_revision=employee_revision,
                rules_fingerprint=rules_fingerprint,
                constraint_snapshot_hash=snapshot_hash,
                reason=force_request.authorization_reason,
                created_at=created,
                expires_at=created + timedelta(hours=24),
            )
            for scope in force_request.requested_overrides
        ]
        force_context = self.context_builder.build(
            week_start,
            base_schedule=base_schedule,
            changes=effective_changes,
            minimize_changes=minimize_changes,
            employees=employee_list,
            allow_history_bootstrap=True,
            user_forced_assignments=force_request.forced_assignments,
            override_scopes=[item.model_dump(mode="json") for item in authorizations],
        )
        logger.info("override_created", extra={"override_count": len(authorizations), "target_week": week_start.isoformat()})
        logger.info("force_solve_started", extra={"target_week": week_start.isoformat(), "override_count": len(authorizations)})
        result = self.solver.solve(
            force_context,
            week_start=week_start,
            schedule_id=self._new_schedule_id(),
            version=version,
            parent_schedule_id=parent_schedule_id,
        )
        if result.status is SolverStatus.INFEASIBLE:
            response = self._infeasible_response(result)
            response["message"] = "Authorized scopes cannot satisfy protected rules or an unapproved hard constraint."
            return response
        if result.schedule is None:
            return {**self._infeasible_response(result), "status": "solver_unknown"}
        response = self._complete_draft(
            context=force_context,
            result=result,
            lineage_id=base_record["lineage_id"] if base_record else result.schedule.schedule_id,
            base_schedule=base_schedule,
            base_version=base_version,
            employee_revision=employee_revision,
            metadata_extra={
                **dict(metadata_extra or {}),
                "force_requested": True,
                "scenario_revision": scenario_revision,
                "force_source_conversation_id": source_conversation_id,
                "force_source_message_id": message_id,
                "force_client_message_id": idempotency_key,
                "rules_fingerprint": rules_fingerprint,
                "constraint_snapshot_hash": snapshot_hash,
                "user_forced_assignments": [
                    item.model_dump(mode="json") for item in force_request.forced_assignments
                ],
            },
            before_commit=before_commit,
            agent_turn_guard=agent_turn_guard,
            authorizations=authorizations,
        )
        logger.info("force_solve_completed", extra={"schedule_id": response.get("schedule_id"), "compliance_status": response.get("compliance_status")})
        return response

    def promote_preview(
        self,
        *,
        week_start: date,
        preview: dict[str, Any],
        changes: list[ScheduleChange],
        metadata_extra: dict[str, Any] | None = None,
        before_commit: Callable[[], None] | None = None,
        agent_turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        """Persist the exact assignments from a validated scenario preview."""
        if not preview.get("strict_feasible") or not isinstance(preview.get("schedule"), dict):
            raise SolverOutputError("当前场景没有可保存的严格可行候选")
        employee_list, employee_revision = self.employees.list_with_revision()
        base_record = self.schedules.current_confirmed_record_for_week(week_start)
        base_schedule = base_record["schedule"] if base_record else None
        base_version = base_schedule.version if base_schedule else None
        validate_changes(changes, employee_list)
        context = self.context_builder.build(
            week_start,
            base_schedule=base_schedule,
            changes=changes,
            minimize_changes=True,
            employees=employee_list,
            allow_history_bootstrap=True,
        )
        schedule = Schedule.model_validate(preview["schedule"]).model_copy(update={
            "schedule_id": self._new_schedule_id(),
            "version": (base_version + 1 if base_version is not None else 1),
            "parent_schedule_id": base_schedule.schedule_id if base_schedule else None,
            "status": ScheduleStatus.DRAFT,
        })
        validation = classify_validation(
            normalize_validation(
                self.validator.validate(schedule, employee_list, context=context, rules=context.rules)
            ),
            schedule.week_start,
        )
        if not validation["passed"]:
            raise SolverOutputError("场景预览在保存前未通过独立校验")
        diff, impact = build_diff(base_schedule, schedule, context.requested_changes)
        metadata = {
            **dict(metadata_extra or {}),
            "solver_status": preview.get("solver_status", "feasible"),
            "metrics": dict(preview.get("metrics") or {}),
            "diff": diff,
            "impact": impact,
            "requested_changes": [item.model_dump(mode="json") for item in changes],
            "employee_revision": employee_revision,
            "scenario_preview_promoted": True,
        }
        if before_commit is not None:
            before_commit()
        self.schedules.save_draft(
            schedule,
            lineage_id=(base_record["lineage_id"] if base_record else schedule.schedule_id),
            base_schedule_id=base_schedule.schedule_id if base_schedule else None,
            base_version=base_version,
            validation=validation,
            metadata=metadata,
            employee_revision=employee_revision,
            agent_turn_guard=agent_turn_guard,
        )
        return {
            "status": "feasible",
            "solver_status": preview.get("solver_status", "feasible"),
            "schedule_id": schedule.schedule_id,
            "version": schedule.version,
            "schedule_status": "draft",
            "schedule": schedule.model_dump(mode="json"),
            "validation": validation,
            "diff": diff,
            "impact": impact,
            "metrics": dict(preview.get("metrics") or {}),
            **compliance_fields(validation, "draft"),
        }

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
        return classify_validation(normalize_validation(result), schedule.week_start)

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
        metadata = record["metadata"]
        source_rules_fingerprint = metadata.get("source_rules_fingerprint")
        rules_changed = (
            source_rules_fingerprint is not None
            and source_rules_fingerprint != fingerprint(self.context_builder.rules.model_dump(mode="json"))
        )
        changes = [ScheduleChange.model_validate(item) for item in metadata.get("requested_changes", [])]
        forced_assignments = [
            Assignment.model_validate(item)
            for item in metadata.get("user_forced_assignments", [])
        ]
        stored_authorizations = [
            OverrideAuthorization.model_validate(item)
            for item in metadata.get("override_authorizations", [])
        ]
        base = (
            self.schedules.get(record["base_schedule_id"])
            if record["base_schedule_id"]
            else None
        )
        strict_context = self.context_builder.build(
            schedule.week_start,
            base_schedule=base,
            changes=changes,
            minimize_changes=bool(base),
            employees=employee_list,
            allow_history_bootstrap=False,
            user_forced_assignments=forced_assignments,
            rule_config=metadata.get("rule_config"),
        )
        rules_fingerprint = fingerprint(strict_context.rules.model_dump(mode="json"))
        snapshot_hash = fingerprint(context_snapshot(strict_context, schedule.week_start))
        scenario_current = True
        source_conversation_id = metadata.get("force_source_conversation_id")
        if source_conversation_id and self.scenarios is not None:
            state = self.scenarios.get(source_conversation_id, schedule.week_start)
            scenario_current = (state.revision if state is not None else 0) == metadata.get("scenario_revision", 0)
        authorizations = [
            authorization
            for authorization in stored_authorizations
            if scenario_current and not rules_changed and authorization_is_active(
                authorization,
                week=schedule.week_start,
                base_schedule_id=record.get("base_schedule_id"),
                base_version=record.get("base_version"),
                scenario_revision=metadata.get("scenario_revision", 0),
                employee_revision=employee_revision,
                rules_fingerprint=rules_fingerprint,
                constraint_snapshot_hash=snapshot_hash,
            ) and authorization.consumed_by_schedule_id == schedule_id
        ]
        if stored_authorizations and len(authorizations) != len(stored_authorizations):
            logger.info(
                "override_stale",
                extra={"schedule_id": schedule_id, "active_authorization_count": len(authorizations)},
            )
        context = self.context_builder.build(
            schedule.week_start,
            base_schedule=base,
            changes=changes,
            minimize_changes=bool(base),
            employees=employee_list,
            allow_history_bootstrap=False,
            user_forced_assignments=forced_assignments,
            rule_config=metadata.get("rule_config"),
            override_scopes=[item.model_dump(mode="json") for item in stored_authorizations],
        )
        result = self.validator.validate(schedule, employee_list, context=context)
        validation = classify_validation(normalize_validation(result), schedule.week_start, authorizations)
        validation["employee_data_stale"] = (
            record["status"] == "draft"
            and stored_revision is not None
            and stored_revision != employee_revision
        )
        validation["rules_data_stale"] = record["status"] == "draft" and rules_changed
        if validation["employee_data_stale"] or validation["rules_data_stale"]:
            validation["confirmable"] = False
        return validation

    def confirm(self, schedule_id: str, version: int) -> dict[str, Any]:
        validation = self.validate_stored(
            schedule_id,
            enforce_employee_revision=True,
        )
        if not validation["confirmable"]:
            raise SolverOutputError("Draft is no longer valid against current employee data")
        confirmed = self.schedules.confirm(schedule_id, version)
        record = self.schedules.get_record(schedule_id) or {}
        metadata = record.get("metadata", {})
        return {
            "status": "confirmed",
            "solver_status": metadata.get("solver_status", "feasible"),
            "schedule_id": confirmed.schedule_id,
            "version": confirmed.version,
            "schedule_status": "confirmed",
            "schedule": confirmed.model_dump(mode="json"),
            "validation": validation,
            "diff": metadata.get("diff"),
            "impact": metadata.get("impact"),
            "metrics": metadata.get("metrics", {}),
            "explanation": metadata.get("explanation"),
            "rule_config": metadata.get("rule_config"),
            **compliance_fields(validation, "confirmed"),
        }

    def cancel(self, schedule_id: str, version: int) -> dict[str, Any]:
        cancelled = self.schedules.cancel(schedule_id, version)
        current = None
        base_schedule_id = cancelled.get("base_schedule_id")
        if base_schedule_id:
            current_schedule = self.schedules.get(base_schedule_id)
            current = current_schedule.model_dump(mode="json") if current_schedule else None
        return {**cancelled, "confirmed_schedule": current}
