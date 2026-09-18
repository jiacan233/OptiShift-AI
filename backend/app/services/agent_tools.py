from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Callable

from ..models import PatchOperation, Schedule, ScheduleChange, ScenarioPatch
from ..repository import EmployeeRepository, ScheduleRepository, ScenarioRepository
from .rules import public_rules
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

    def get_current_schedule(self, *, target_week: date) -> dict[str, Any]:
        confirmed, draft = self.schedules.current_records_for_week(target_week)
        display = draft or confirmed
        return {
            "target_week": target_week.isoformat(),
            "confirmed": _serialize_record(confirmed),
            "draft": _serialize_record(draft),
            "display": _serialize_record(display),
        }

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
        expected_revision: int | None = None,
        employee_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        current = self.get_current_schedule(target_week=target_week)
        base = current.get("display")
        base_schedule = Schedule.model_validate(base["schedule"]) if base else None
        grouped: dict[str, list] = {}
        for change in changes:
            grouped.setdefault(change.employee_id, []).append(change.day)
        if operation == "clear":
            for employee_id in employee_ids or []:
                grouped.setdefault(employee_id, [])
        state = None
        for employee_id, days in grouped.items():
            change_type = changes[0].type if changes else "leave"
            # Removing availability restores the scenario's leave patch; the
            # reducer must address the existing leave constraint rather than
            # creating a separate `available` bucket.
            if operation == "remove" and change_type.value == "available":
                change_type = "leave"
            state = self.scenarios.upsert_patch(
                conversation_id,
                target_week,
                ScenarioPatch(
                    employee_id=employee_id,
                    operation=operation,
                    days=days,
                    change_type=change_type,
                ),
                expected_revision=expected_revision if state is None else None,
            )
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
            "generate_schedule": self.generate_schedule,
            "replan_schedule": self.replan_schedule,
            "get_scenario": self.get_scenario,
            "preview_scenario": self.preview_scenario,
            "save_scenario": self.save_scenario,
        }
        tool = tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown agent tool: {tool_name}")
        return tool(**inputs)
