from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..database import Database, utc_now
from ..models import Employee


class EmployeeNotFoundError(LookupError):
    pass


class ImmutableEmployeeFieldError(ValueError):
    pass


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


class EmployeeRepository:
    MUTABLE_FIELDS = {"role", "available_days", "leave_days", "preferred_shift"}

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Employee:
        return Employee(
            id=row["id"],
            role=row["role"],
            skills=json.loads(row["skills_json"]),
            available_days=json.loads(row["available_days_json"]),
            leave_days=json.loads(row["leave_days_json"]),
            preferred_shift=row["preferred_shift"],
        )

    def list(self) -> list[Employee]:
        employees, _revision = self.list_with_revision()
        return employees

    def list_with_revision(self) -> tuple[list[Employee], int]:
        """Return employee rows and the revision from one SQLite snapshot."""
        with self.database.transaction() as connection:
            revision_row = connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'employee_revision'"
            ).fetchone()
            rows = connection.execute("SELECT * FROM employees ORDER BY id").fetchall()
        revision = int(revision_row["value"]) if revision_row is not None else 0
        return [self._from_row(row) for row in rows], revision

    @staticmethod
    def _increment_revision(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO system_metadata (key, value) VALUES ('employee_revision', '1')
            ON CONFLICT(key) DO UPDATE
            SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            """
        )

    def get(self, employee_id: str) -> Employee | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def create(self, employee: Employee) -> Employee:
        payload = employee.model_dump(mode="json")
        timestamp = utc_now()
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """
                    INSERT INTO employees (
                        id, role, skills_json, available_days_json, leave_days_json,
                        preferred_shift, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["id"],
                        payload["role"],
                        json.dumps(payload["skills"]),
                        json.dumps(payload["available_days"]),
                        json.dumps(payload["leave_days"]),
                        payload.get("preferred_shift"),
                        timestamp,
                        timestamp,
                    ),
                )
                self._increment_revision(connection)
        except sqlite3.IntegrityError as exc:
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
        with self.database.transaction(immediate=True) as connection:
            current_row = connection.execute(
                "SELECT * FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            if current_row is None:
                raise EmployeeNotFoundError(employee_id)
            current = self._from_row(current_row)
            candidate = current.model_copy(update=changes)
            candidate = Employee.model_validate(candidate.model_dump())
            payload = candidate.model_dump(mode="json")
            connection.execute(
                """
                UPDATE employees
                SET role = ?, available_days_json = ?, leave_days_json = ?,
                    preferred_shift = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["role"],
                    json.dumps(payload["available_days"]),
                    json.dumps(payload["leave_days"]),
                    payload.get("preferred_shift"),
                    utc_now(),
                    employee_id,
                ),
            )
            self._increment_revision(connection)
        return candidate

    def delete(self, employee_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            result = connection.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
            if result.rowcount == 0:
                raise EmployeeNotFoundError(employee_id)
            self._increment_revision(connection)
