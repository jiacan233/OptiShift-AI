from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter

from ..models import Day, Shift
from .dependencies import employee_repository


router = APIRouter(prefix="/api/employees", tags=["employees"])


class EmployeePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available_days: list[Day] | None = None
    leave_days: list[Day] | None = None
    preferred_shift: Shift | None = None


@router.get("")
def list_employees() -> dict:
    return {"employees": [employee.model_dump(mode="json") for employee in employee_repository.list()]}


@router.patch("/{employee_id}")
def update_employee(employee_id: str, patch: EmployeePatch) -> dict:
    changes = patch.model_dump(exclude_unset=True)
    employee = employee_repository.update(employee_id, changes)
    return employee.model_dump(mode="json")
