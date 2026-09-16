from __future__ import annotations

import re
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
        normalized = query.strip().lower()
        exact_ids = {
            match.upper() for match in re.findall(r"\b[eE]\d{1,4}\b", query)
        }
        if exact_ids:
            candidates = [employee for employee in employees if employee.id in exact_ids]
        else:
            candidates = list(employees)
            if any(token in normalized for token in ("兼职", "part-time", "part time")):
                candidates = [e for e in candidates if "part" in e.role.lower() or "兼职" in e.role]
            if any(token in normalized for token in ("店长", "经理", "manager")):
                candidates = [e for e in candidates if "manager" in {s.value for s in e.skills}]
            if day is not None:
                candidates = [
                    e for e in candidates if day in e.available_days and day not in e.leave_days
                ]

        if not candidates:
            return Resolution(status="entity_not_found", candidates=[])
        if len(candidates) == 1:
            return Resolution(status="resolved", candidates=candidates, employee=candidates[0])
        return Resolution(status="clarification_required", candidates=candidates)

    @staticmethod
    def validate_selected(employee_id: str, employees: list[Employee]) -> Employee:
        employee = next((item for item in employees if item.id == employee_id), None)
        if employee is None:
            raise EntitySelectionError(f"Employee {employee_id} does not exist")
        return employee
