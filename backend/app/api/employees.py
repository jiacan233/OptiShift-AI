from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, HTTPException

from ..models import Day, Shift, Employee
from .dependencies import employee_repository


router = APIRouter(prefix="/api/employees", tags=["employees"])


class EmployeePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available_days: list[Day] | None = None
    leave_days: list[Day] | None = None
    preferred_shift: Shift | None = None


class EmployeeCreate(Employee):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    role: str = Field(min_length=1, max_length=64)


@router.post("", status_code=201)
def create_employee(body: EmployeeCreate) -> dict:
    employee = Employee.model_validate(body.model_dump())
    try:
        return employee_repository.create(employee).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="员工编号已存在，请使用其他编号。") from exc


@router.get("")
def list_employees() -> dict:
    return {"employees": [employee.model_dump(mode="json") for employee in employee_repository.list()]}


@router.patch("/{employee_id}")
def update_employee(employee_id: str, patch: EmployeePatch) -> dict:
    changes = patch.model_dump(exclude_unset=True)
    employee = employee_repository.update(employee_id, changes)
    return employee.model_dump(mode="json")
