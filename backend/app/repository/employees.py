from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import Database, utc_now
from ..models import Employee
from ..models.orm import EmployeeRecord, SystemMetadataRecord


class EmployeeNotFoundError(LookupError):
    pass


class ImmutableEmployeeFieldError(ValueError):
    pass


class EmployeeRepository:
    MUTABLE_FIELDS = {"role", "available_days", "leave_days", "preferred_shift"}

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _from_record(record: EmployeeRecord) -> Employee:
        return Employee(
            id=record.id,
            role=record.role,
            skills=record.skills,
            available_days=record.available_days,
            leave_days=record.leave_days,
            preferred_shift=record.preferred_shift,
        )

    @staticmethod
    def _increment_revision(session: Session) -> None:
        statement = select(SystemMetadataRecord).where(
            SystemMetadataRecord.key == "employee_revision"
        )
        if session.bind is not None and session.bind.dialect.name != "sqlite":
            statement = statement.with_for_update()
        revision = session.scalar(statement)
        if revision is None:
            session.add(SystemMetadataRecord(key="employee_revision", value="1"))
        else:
            revision.value = str(int(revision.value) + 1)

    def list(self) -> list[Employee]:
        employees, _revision = self.list_with_revision()
        return employees

    def list_with_revision(self) -> tuple[list[Employee], int]:
        with self.database.transaction() as session:
            revision = session.get(SystemMetadataRecord, "employee_revision")
            records = session.scalars(
                select(EmployeeRecord).order_by(EmployeeRecord.id)
            ).all()
            value = int(revision.value) if revision is not None else 0
            return [self._from_record(record) for record in records], value

    def get(self, employee_id: str) -> Employee | None:
        with self.database.transaction() as session:
            record = session.get(EmployeeRecord, employee_id)
            return self._from_record(record) if record else None

    def create(self, employee: Employee) -> Employee:
        payload = employee.model_dump(mode="json")
        timestamp = utc_now()
        try:
            with self.database.transaction(immediate=True) as session:
                session.add(
                    EmployeeRecord(
                        id=payload["id"],
                        role=payload["role"],
                        skills=payload["skills"],
                        available_days=payload["available_days"],
                        leave_days=payload["leave_days"],
                        preferred_shift=payload.get("preferred_shift"),
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                self._increment_revision(session)
        except IntegrityError as exc:
            raise ValueError(f"Employee {employee.id} already exists") from exc
        return employee

    def update(self, employee_id: str, changes: dict[str, Any]) -> Employee:
        if "skills" in changes:
            raise ImmutableEmployeeFieldError(
                "skills are master data and cannot be changed through the employee update API"
            )
        unknown = set(changes) - self.MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Unsupported employee fields: {', '.join(sorted(unknown))}")

        with self.database.transaction(immediate=True) as session:
            statement = select(EmployeeRecord).where(EmployeeRecord.id == employee_id)
            if self.database.dialect_name != "sqlite":
                statement = statement.with_for_update()
            record = session.scalar(statement)
            if record is None:
                raise EmployeeNotFoundError(employee_id)
            current = self._from_record(record)
            candidate = Employee.model_validate(current.model_copy(update=changes).model_dump())
            payload = candidate.model_dump(mode="json")
            record.role = payload["role"]
            record.available_days = payload["available_days"]
            record.leave_days = payload["leave_days"]
            record.preferred_shift = payload.get("preferred_shift")
            record.updated_at = utc_now()
            self._increment_revision(session)
            return candidate

    def delete(self, employee_id: str) -> None:
        with self.database.transaction(immediate=True) as session:
            record = session.get(EmployeeRecord, employee_id)
            if record is None:
                raise EmployeeNotFoundError(employee_id)
            session.delete(record)
            self._increment_revision(session)
