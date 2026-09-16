from __future__ import annotations

from ..models import Employee, ScheduleChange


class BusinessValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("; ".join(error["message"] for error in errors))


def validate_changes(changes: list[ScheduleChange], employees: list[Employee]) -> None:
    employee_ids = {employee.id for employee in employees}
    errors = []
    for index, change in enumerate(changes):
        if change.employee_id not in employee_ids:
            errors.append(
                {
                    "field": f"changes.{index}.employee_id",
                    "message": f"Employee {change.employee_id} does not exist",
                }
            )
    if errors:
        raise BusinessValidationError(errors)
