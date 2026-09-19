from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Callable

from ..execution import traced
from ..models import (
    ChangeType,
    ForceRequest,
    PatchOperation,
    ScenarioPatch,
    Schedule,
    ScheduleChange,
)
from ..repository import EmployeeRepository, ScenarioRepository, ScheduleRepository
from .rules import public_rules
from .read_query import ReadQueryPlan
from .read_analysis import analyze_snapshot, counterfactual_snapshot, validate_snapshot
from .diff_service import build_diff
from .scheduling_service import SchedulingService


def _serialize_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    result = dict(record)
    schedule = result.get("schedule")
    if isinstance(schedule, Schedule):
        result["schedule"] = schedule.model_dump(mode="json")
    return result


class AgentTools:
    """Deterministic tool boundary. The LLM never receives repository access."""

    def __init__(
        self,
        employees: EmployeeRepository,
        schedules: ScheduleRepository,
        scheduling: SchedulingService,
        scenarios: ScenarioRepository,
    ) -> None:
        self.employees = employees
        self.schedules = schedules
        self.scheduling = scheduling
        self.scenarios = scenarios

    @traced("load_schedule")
    def get_current_schedule(self, *, target_week: date, version: int | None = None) -> dict[str, Any]:
        confirmed, draft = self.schedules.current_records_for_week(target_week)
        display = draft or confirmed
        if version is not None:
            selected = next((r for r in self.schedules.versions_for_week(target_week) if r["version"] == version), None)
            display = self.schedules.get_record(selected["schedule_id"]) if selected else None
        return {
            "target_week": target_week.isoformat(),
            "confirmed": _serialize_record(confirmed),
            "draft": _serialize_record(draft),
            "display": _serialize_record(display),
        }

    def _read_snapshot(self, *, target_week: date, snapshot: dict | None):
        schedule = Schedule.model_validate(snapshot["schedule"]) if snapshot else None
        if schedule and schedule.week_start != target_week:
            raise ValueError("Snapshot does not belong to the target week")
        metadata = (snapshot or {}).get("metadata") or {}
        context = self.scheduling.context_builder.build(
            target_week, base_schedule=schedule,
            changes=[ScheduleChange.model_validate(c) for c in metadata.get("requested_changes", [])],
            allow_history_bootstrap=False, allow_ephemeral_known_empty=True,
            # Read facts and the independent validator share the current RuleConfig.
            rule_config=self.scheduling.context_builder.rules.model_dump(mode="json"),
        )
        return schedule, context

    @traced("read_analysis")
    def analyze_staffing(self, *, target_week: date, plan: dict, snapshot: dict | None,
                         conversation_id: str | None = None) -> dict[str, Any]:
        query = ReadQueryPlan.model_validate(plan)
        schedule, context = self._read_snapshot(target_week=target_week, snapshot=snapshot)
        result = analyze_snapshot(schedule, context, query) if schedule else {
            "status": "no_schedule", "target_week": target_week.isoformat(), "schedule_id": None,
            "version": query.version, "schedule_status": None, "slots": [], "read_only": True,
            "source": "explicit_version" if query.version else "display_schedule",
            "rules": context.rules.model_dump(mode="json"),
        }
        if query.question_type == "schedule_difference" and schedule:
            previous = sorted((r for r in self.schedules.versions_for_week(target_week)
                               if r["version"] < schedule.version), key=lambda r: r["version"], reverse=True)
            base = self.schedules.get(previous[0]["schedule_id"], include_cancelled=True) if previous else None
            result["comparison_version"] = base.version if base else None
            result["difference"] = build_diff(base, schedule)[0] if base else None
        if query.question_type == "feasibility_explanation":
            from ..core import HistoryUnavailableError
            from ..solver.primary_solver import PrimarySolver
            if conversation_id:
                state = self.scenarios.get(conversation_id, target_week)
                if state:
                    context.requested_changes = [ScheduleChange(employee_id=p.employee_id, type=p.change_type, day=d)
                                                 for p in state.patches for d in p.days]
                    result["scenario_revision"] = state.revision
            try:
                solved = PrimarySolver().solve(context, week_start=target_week)
                result["feasibility"] = {
                    "status": solved.status.value,
                    "validation": validate_snapshot(solved.schedule, context) if solved.schedule else None,
                    "diagnosis": solved.diagnosis.model_dump(mode="json") if solved.diagnosis else None,
                    "scope": "current_rules_employees_and_scenario",
                }
            except HistoryUnavailableError:
                result["feasibility"] = {"status": "history_unavailable", "diagnosis": None}
        return result

    @traced("counterfactual")
    def analyze_counterfactual(self, *, target_week: date, plan: dict, snapshot: dict | None,
                               conversation_id: str | None = None) -> dict[str, Any]:
        query = ReadQueryPlan.model_validate(plan)
        schedule, context = self._read_snapshot(target_week=target_week, snapshot=snapshot)
        if schedule is None:
            return {"status": "no_schedule", "target_week": target_week.isoformat(), "read_only": True}
        return counterfactual_snapshot(schedule, context, query)

    def get_scenario(self, *, conversation_id: str, target_week: date) -> dict[str, Any]:
        state = self.scenarios.get(conversation_id, target_week)
        return {
            "scenario_revision": state.revision if state else 0,
            "patches": [item.model_dump(mode="json") for item in state.patches] if state else [],
        }

    def preview_scenario(
        self,
        *,
        conversation_id: str,
        target_week: date,
        changes: list[ScheduleChange],
        operation: str = "add",
        operations: list[dict[str, Any]] | None = None,
        expected_revision: int | None = None,
        employee_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        current = self.get_current_schedule(target_week=target_week)
        base = current.get("display")
        base_schedule = Schedule.model_validate(base["schedule"]) if base else None
        if operations:
            # Preserve the model's ordered, per-item operation semantics.  Do
            # not regroup a mixed ADD/REMOVE/SET request into one global action.
            patches = []
            for item in operations:
                item_operation = str(item.get("operation") or operation)
                item_day = item.get("day")
                item_type = ChangeType(item.get("type") or ChangeType.LEAVE.value)
                if item_operation == "remove" and item_type is ChangeType.AVAILABLE:
                    item_type = ChangeType.LEAVE
                patches.append(ScenarioPatch(
                    employee_id=str(item["employee_id"]),
                    operation=item_operation,
                    days=[item_day] if item_day is not None else [],
                    change_type=item_type,
                ))
        else:
            grouped: dict[tuple[str, ChangeType], list] = {}
            for change in changes:
                change_type = change.type
                # AVAILABLE is the structured representation of removing a leave
                # condition; keep the stored constraint type stable for the reducer.
                if operation == "remove" and change_type.value == "available":
                    change_type = ChangeType.LEAVE
                grouped.setdefault((change.employee_id, change_type), []).append(change.day)
            patches = [
                ScenarioPatch(
                    employee_id=employee_id,
                    operation=operation,
                    days=list(dict.fromkeys(days)),
                    change_type=change_type,
                )
                for (employee_id, change_type), days in grouped.items()
            ]
        if operation == "clear":
            patches.extend(
                ScenarioPatch(employee_id=employee_id, operation=operation, days=[])
                for employee_id in (employee_ids or [])
                if not any(item.employee_id == employee_id for item in patches)
            )
        state = self.scenarios.upsert_patches(
            conversation_id,
            target_week,
            patches,
            expected_revision=expected_revision,
        ) if patches else self.scenarios.get(conversation_id, target_week)
        state = state or self.scenarios.get(conversation_id, target_week)
        patches = state.patches if state else []
        result = self.scheduling.preview_scenario(
            week_start=target_week,
            patches=patches,
            base_schedule=base_schedule,
        )
        result["scenario_revision"] = state.revision if state else 0
        result["target_week"] = target_week.isoformat()
        result["scenario_patches"] = [item.model_dump(mode="json") for item in patches]
        for suggestion in result.get("suggestions", []):
            suggestion["based_on_scenario_revision"] = result["scenario_revision"]
            suggestion["target_week"] = target_week.isoformat()
            suggestion["based_on_schedule_id"] = (base or {}).get("schedule_id")
            suggestion["based_on_version"] = (base or {}).get("version")
        self.scenarios.save_results(
            conversation_id,
            target_week,
            strict_result={"strict_feasible": result.get("strict_feasible", False)},
            preview_result=result,
        )
        return result

    def save_scenario(
        self,
        *,
        conversation_id: str,
        target_week: date,
        source_conversation_id: str,
        source_client_message_id: str,
        source_user_message_id: str,
        _before_commit: Callable[[], None] | None = None,
        _turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        state = self.scenarios.get(conversation_id, target_week)
        if state is None:
            raise ValueError("当前周没有可保存的场景试排")
        preview = self.scenarios.get_preview_result(conversation_id, target_week)
        if preview and preview.get("strict_feasible") and isinstance(preview.get("schedule"), dict):
            changes = [
                ScheduleChange(employee_id=patch.employee_id, type=patch.change_type, day=day)
                for patch in state.patches
                for day in patch.days
            ]
            return self.scheduling.promote_preview(
                week_start=target_week,
                preview=preview,
                changes=changes,
                metadata_extra={
                    "agent_conversation_id": source_conversation_id,
                    "agent_client_message_id": source_client_message_id,
                    "agent_user_message_id": source_user_message_id,
                    "scenario_revision": state.revision,
                    "scenario_persisted": True,
                },
                before_commit=_before_commit,
                agent_turn_guard=_turn_guard,
            )
        changes = [
            ScheduleChange(employee_id=patch.employee_id, type=patch.change_type, day=day)
            for patch in state.patches
            for day in patch.days
        ]
        return self.scheduling.generate(
            week_start=target_week,
            changes=changes,
            prompt="",
            metadata_extra={
                "agent_conversation_id": source_conversation_id,
                "agent_client_message_id": source_client_message_id,
                "agent_user_message_id": source_user_message_id,
                "scenario_revision": state.revision,
                "scenario_persisted": True,
            },
            before_commit=_before_commit,
            agent_turn_guard=_turn_guard,
        )

    @traced("load_schedule")
    def get_schedule_context(self, *, target_week: date) -> dict[str, Any]:
        current = self.get_current_schedule(target_week=target_week)
        display = current["display"]
        context = self.scheduling.context_builder.build(
            target_week,
            base_schedule=(
                Schedule.model_validate(display["schedule"]) if display is not None else None
            ),
            allow_history_bootstrap=False,
            allow_ephemeral_known_empty=True,
        )
        employees, revision = self.employees.list_with_revision()
        return {
            **current,
            "employees": [employee.model_dump(mode="json") for employee in employees],
            "employee_revision": revision,
            "rules": public_rules(context.rules),
            "history_status": context.history_status.value,
            "history_schedule_id": context.history_schedule_id,
            "history_schedule_version": context.history_schedule_version,
            "previous_week_assignments": [
                item.model_dump(mode="json") for item in context.previous_days
            ],
            "metrics": (display or {}).get("metadata", {}).get("metrics", {}),
        }

    def get_employee(self, *, employee_id: str) -> dict[str, Any]:
        employee = self.employees.get(employee_id)
        if employee is None:
            raise ValueError(f"Employee {employee_id} does not exist")
        return employee.model_dump(mode="json")

    def get_rules(self) -> dict[str, Any]:
        return {"rules": public_rules(self.scheduling.context_builder.rules)}

    def validate_schedule(self, *, target_week: date) -> dict[str, Any]:
        confirmed, draft = self.schedules.current_records_for_week(target_week)
        display = draft or confirmed
        if display is None:
            return {
                "status": "no_schedule",
                "target_week": target_week.isoformat(),
                "validation": None,
            }
        validation = self.scheduling.validate_stored(display["schedule_id"])
        return {
            "status": "validated",
            "target_week": target_week.isoformat(),
            "schedule_id": display["schedule_id"],
            "version": display["version"],
            "schedule_status": display["status"],
            "validation": validation,
        }

    def analyze_schedule(
        self,
        *,
        target_week: date,
        changes: list[ScheduleChange] | None = None,
    ) -> dict[str, Any]:
        requested_changes = list(changes or [])
        confirmed, draft = self.schedules.current_records_for_week(target_week)
        display = draft or confirmed
        if display is None:
            return {
                "status": "no_schedule",
                "target_week": target_week.isoformat(),
                "metrics": {},
                "workload": {},
                "coverage": {},
                "validation": None,
                "requested_changes": [
                    item.model_dump(mode="json") for item in requested_changes
                ],
                "impact": {
                    "affected_assignments": [],
                    "affected_count": 0,
                    "affected_slots": [],
                    "requires_replan": bool(requested_changes),
                },
            }
        schedule: Schedule = display["schedule"]
        employees = {employee.id: employee for employee in self.employees.list()}
        workload = Counter(item.employee_id for item in schedule.assignments)
        coverage: dict[str, dict[str, int]] = {}
        preferred = 0
        for assignment in schedule.assignments:
            employee = employees.get(assignment.employee_id)
            key = f"{assignment.day.value}:{assignment.shift.value}"
            slot = coverage.setdefault(
                key, {"staff": 0, "manager": 0, "beverage": 0, "cashier": 0}
            )
            slot["staff"] += 1
            if employee is not None:
                skills = {skill.value for skill in employee.skills}
                for skill in ("manager", "beverage", "cashier"):
                    slot[skill] += int(skill in skills)
                preferred += int(employee.preferred_shift == assignment.shift)
        validation = self.scheduling.validate_stored(schedule.schedule_id)
        metadata_metrics = dict(display.get("metadata", {}).get("metrics", {}))
        metadata_metrics.setdefault(
            "preference_rate",
            preferred / len(schedule.assignments) if schedule.assignments else 0.0,
        )
        values = list(workload.values()) or [0]
        metadata_metrics.setdefault("workload_gap", max(values) - min(values))
        affected_assignments = [
            assignment.model_dump(mode="json")
            for assignment in schedule.assignments
            if any(
                change.employee_id == assignment.employee_id
                and change.day == assignment.day
                and (
                    change.type.value in {"leave", "unavailable"}
                    or (
                        change.type.value == "unassign"
                        and change.shift == assignment.shift
                    )
                )
                for change in requested_changes
            )
        ]
        affected_slots = sorted(
            {f"{item['day']}:{item['shift']}" for item in affected_assignments}
        )
        return {
            "status": "analyzed",
            "target_week": target_week.isoformat(),
            "schedule_id": schedule.schedule_id,
            "version": schedule.version,
            "schedule_status": display["status"],
            "metrics": metadata_metrics,
            "workload": dict(sorted(workload.items())),
            "coverage": coverage,
            "validation": validation,
            "requested_changes": [
                item.model_dump(mode="json") for item in requested_changes
            ],
            "impact": {
                "affected_assignments": affected_assignments,
                "affected_count": len(affected_assignments),
                "affected_slots": affected_slots,
                "requires_replan": bool(affected_assignments),
            },
        }

    def generate_schedule(
        self,
        *,
        target_week: date,
        changes: list[ScheduleChange],
        source_conversation_id: str,
        source_client_message_id: str,
        source_user_message_id: str,
        _before_commit: Callable[[], None] | None = None,
        _turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        return self.scheduling.generate(
            week_start=target_week,
            changes=changes,
            prompt="",
            metadata_extra={
                "agent_conversation_id": source_conversation_id,
                "agent_client_message_id": source_client_message_id,
                "agent_user_message_id": source_user_message_id,
            },
            before_commit=_before_commit,
            agent_turn_guard=_turn_guard,
        )

    def force_generate_schedule(
        self,
        *,
        target_week: date,
        force_request: ForceRequest,
        changes: list[ScheduleChange],
        source_conversation_id: str,
        source_client_message_id: str,
        source_user_message_id: str,
        expected_base: tuple[str | None, int | None] | None = None,
        _before_commit: Callable[[], None] | None = None,
        _turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        scenario = self.scenarios.get(source_conversation_id, target_week)
        scenario_changes = [
            ScheduleChange(employee_id=patch.employee_id, type=patch.change_type, day=day)
            for patch in (scenario.patches if scenario else [])
            for day in patch.days
        ]
        return self.scheduling.force_generate(
            week_start=target_week,
            force_request=force_request,
            changes=scenario_changes,
            source_conversation_id=source_conversation_id,
            source_message_id=source_user_message_id,
            client_message_id=source_client_message_id,
            scenario_revision=scenario.revision if scenario is not None else 0,
            expected_base=expected_base,
            metadata_extra={
                "agent_conversation_id": source_conversation_id,
                "agent_client_message_id": source_client_message_id,
                "agent_user_message_id": source_user_message_id,
            },
            before_commit=_before_commit,
            agent_turn_guard=_turn_guard,
        )

    def replan_schedule(
        self,
        *,
        target_week: date,
        changes: list[ScheduleChange],
        source_conversation_id: str,
        source_client_message_id: str,
        source_user_message_id: str,
        minimize_changes: bool = True,
        _before_commit: Callable[[], None] | None = None,
        _turn_guard: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        confirmed = self.schedules.current_confirmed_record_for_week(target_week)
        if confirmed is None:
            raise ValueError("There is no confirmed schedule to replan for this week")
        return self.scheduling.replan(
            base_schedule_id=confirmed["schedule_id"],
            base_version=confirmed["version"],
            changes=changes,
            minimize_changes=minimize_changes,
            prompt="",
            metadata_extra={
                "agent_conversation_id": source_conversation_id,
                "agent_client_message_id": source_client_message_id,
                "agent_user_message_id": source_user_message_id,
            },
            before_commit=_before_commit,
            agent_turn_guard=_turn_guard,
        )

    def run(self, tool_name: str, **inputs: Any) -> dict[str, Any]:
        tools = {
            "get_current_schedule": self.get_current_schedule,
            "get_schedule_context": self.get_schedule_context,
            "get_employee": self.get_employee,
            "get_rules": self.get_rules,
            "validate_schedule": self.validate_schedule,
            "analyze_schedule": self.analyze_schedule,
            "analyze_staffing": self.analyze_staffing,
            "analyze_counterfactual": self.analyze_counterfactual,
            "generate_schedule": self.generate_schedule,
            "force_generate_schedule": self.force_generate_schedule,
            "replan_schedule": self.replan_schedule,
            "get_scenario": self.get_scenario,
            "preview_scenario": self.preview_scenario,
            "save_scenario": self.save_scenario,
        }
        tool = tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown agent tool: {tool_name}")
        return tool(**inputs)
