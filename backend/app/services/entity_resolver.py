from __future__ import annotations

from dataclasses import dataclass

from ..models import Day, Employee


class EntitySelectionError(LookupError, ValueError):
    """Invalid master-data selection exposed as a client validation error."""


@dataclass(frozen=True)
class Resolution:
    status: str
    candidates: list[Employee]
    employee: Employee | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "employee": self.employee.model_dump(mode="json") if self.employee else None,
            "candidates": [
                {
                    "employee_id": employee.id,
                    "id": employee.id,
                    "role": employee.role,
                    "context": {
                        "available_days": [day.value for day in employee.available_days],
                        "leave_days": [day.value for day in employee.leave_days],
                    },
                }
                for employee in self.candidates
            ],
        }


class EntityResolver:
    """Resolve only against real employee master data; never invent an id."""

    def resolve(
        self, query: str, employees: list[Employee], *, day: Day | None = None
    ) -> Resolution:
        from .dialogue_parser import parse_command
        from .llm_client import AgentLLMClient
        from ..models.dialogue import DialogueState
        command = parse_command(query, DialogueState(), employees, AgentLLMClient())
        ids = {eid for edit in command.edits for eid in edit.employee_ids}
        if command.read_query:
            ids.update(command.read_query.employee_ids)
        candidates = [e for e in employees if e.id in ids]
        if command.clarification or len(candidates) != 1:
            return Resolution(status="clarification_required", candidates=candidates)
        return Resolution(status="resolved", candidates=candidates, employee=candidates[0])

    @staticmethod
    def validate_selected(employee_id: str, employees: list[Employee]) -> Employee:
        employee = next((item for item in employees if item.id == employee_id), None)
        if employee is None:
            raise EntitySelectionError(f"Employee {employee_id} does not exist")
        return employee
