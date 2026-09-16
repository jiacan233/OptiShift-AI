from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from ..database import Database, utc_now
from ..models import Assignment, HistoryStatus, Schedule


class ScheduleNotFoundError(LookupError):
    pass


class DraftNotFoundError(ScheduleNotFoundError):
    pass


class InvalidScheduleStateError(ValueError):
    pass


class VersionConflictError(RuntimeError):
    def __init__(self, current_version: int | None, base_version: int | None) -> None:
        self.current_version = current_version
        self.base_version = base_version
        super().__init__(
            f"Schedule version conflict: current={current_version}, base={base_version}"
        )


class ScheduleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _load_assignments(connection: sqlite3.Connection, schedule_id: str) -> list[Assignment]:
        rows = connection.execute(
            """
            SELECT employee_id, day, shift FROM assignments
            WHERE schedule_id = ? ORDER BY day, shift, employee_id
            """,
            (schedule_id,),
        ).fetchall()
        return [Assignment(**dict(row)) for row in rows]

    @classmethod
    def _schedule_from_row(
        cls, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Schedule:
        return Schedule(
            schedule_id=row["schedule_id"],
            version=row["version"],
            parent_schedule_id=row["parent_schedule_id"],
            status=row["status"],
            week_start=date.fromisoformat(row["week_start"]),
            assignments=cls._load_assignments(connection, row["schedule_id"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_metadata(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schedule_id": row["schedule_id"],
            "lineage_id": row["lineage_id"],
            "version": row["version"],
            "parent_schedule_id": row["parent_schedule_id"],
            "base_schedule_id": row["base_schedule_id"],
            "base_version": row["base_version"],
            "status": row["status"],
            "week_start": row["week_start"],
            "validation": json.loads(row["validation_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "confirmed_at": row["confirmed_at"],
            "cancelled_at": row["cancelled_at"],
        }

    @staticmethod
    def _current_confirmed_row(
        connection: sqlite3.Connection, week_start: date | str
    ) -> sqlite3.Row | None:
        week_value = week_start.isoformat() if isinstance(week_start, date) else week_start
        return connection.execute(
            """
            SELECT * FROM schedules
            WHERE week_start = ? AND status = 'confirmed'
            ORDER BY confirmed_at DESC, created_at DESC, schedule_id DESC
            LIMIT 1
            """,
            (week_value,),
        ).fetchone()

    @staticmethod
    def _employee_revision(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM system_metadata WHERE key = 'employee_revision'"
        ).fetchone()
        return int(row["value"]) if row is not None else 0

    @staticmethod
    def _assert_expected_employee_revision(
        connection: sqlite3.Connection, expected_revision: int | None
    ) -> None:
        if expected_revision is None:
            return
        if ScheduleRepository._employee_revision(connection) != expected_revision:
            raise InvalidScheduleStateError(
                "Employee master data changed while the schedule was being prepared"
            )

    @classmethod
    def _assert_current_week_base(
        cls,
        connection: sqlite3.Connection,
        *,
        week_start: date | str,
        base_schedule_id: str | None,
        base_version: int | None,
    ) -> sqlite3.Row | None:
        current = cls._current_confirmed_row(connection, week_start)
        current_version = current["version"] if current is not None else None
        if base_schedule_id is None:
            if current is not None:
                raise VersionConflictError(current_version, None)
            return None
        if (
            current is None
            or current["schedule_id"] != base_schedule_id
            or current["version"] != base_version
        ):
            raise VersionConflictError(current_version, base_version)
        return current

    @classmethod
    def _assert_history_dependency(
        cls,
        connection: sqlite3.Connection,
        *,
        week_start: date | str,
        metadata: dict[str, Any],
    ) -> None:
        week = (
            week_start
            if isinstance(week_start, date)
            else date.fromisoformat(week_start)
        )
        expected_id = metadata.get("history_schedule_id")
        expected_version = metadata.get("history_schedule_version")
        current = cls._current_confirmed_row(connection, week - timedelta(days=7))
        if expected_id is not None:
            current_id = current["schedule_id"] if current is not None else None
            current_version = current["version"] if current is not None else None
            if current_id != expected_id or current_version != expected_version:
                raise VersionConflictError(current_version, expected_version)
            return

        if metadata.get("history_status") == HistoryStatus.KNOWN_EMPTY.value:
            anchor = connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'initial_known_empty_week'"
            ).fetchone()
            if current is not None or anchor is None or anchor["value"] != week.isoformat():
                raise InvalidScheduleStateError(
                    "The known-empty history boundary changed; regenerate the draft"
                )

    def save_draft(
        self,
        schedule: Schedule,
        *,
        lineage_id: str,
        base_schedule_id: str | None,
        base_version: int | None,
        validation: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        employee_revision: int | None = None,
    ) -> Schedule:
        payload = schedule.model_dump(mode="json")
        metadata_payload = dict(metadata or {})
        if employee_revision is not None:
            metadata_payload["employee_revision"] = employee_revision
        with self.database.transaction(immediate=True) as connection:
            current = self._assert_current_week_base(
                connection,
                week_start=payload["week_start"],
                base_schedule_id=base_schedule_id,
                base_version=base_version,
            )
            if current is not None and (
                current["lineage_id"] != lineage_id
                or schedule.parent_schedule_id != base_schedule_id
                or schedule.version != base_version + 1
            ):
                raise VersionConflictError(current["version"], base_version)
            if current is None and (
                base_schedule_id is not None
                or base_version is not None
                or schedule.parent_schedule_id is not None
                or schedule.version != 1
            ):
                raise VersionConflictError(None, base_version)
            self._assert_expected_employee_revision(connection, employee_revision)
            self._assert_history_dependency(
                connection,
                week_start=payload["week_start"],
                metadata=metadata_payload,
            )
            connection.execute(
                """
                INSERT INTO schedules (
                    schedule_id, lineage_id, version, parent_schedule_id,
                    base_schedule_id, base_version, status, week_start,
                    validation_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
                """,
                (
                    schedule.schedule_id,
                    lineage_id,
                    schedule.version,
                    schedule.parent_schedule_id,
                    base_schedule_id,
                    base_version,
                    payload["week_start"],
                    json.dumps(validation),
                    json.dumps(metadata_payload),
                    payload["created_at"],
                ),
            )
            connection.executemany(
                """
                INSERT INTO assignments (schedule_id, employee_id, day, shift)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        schedule.schedule_id,
                        assignment["employee_id"],
                        assignment["day"],
                        assignment["shift"],
                    )
                    for assignment in payload["assignments"]
                ],
            )
        return schedule

    def get(self, schedule_id: str, *, include_cancelled: bool = False) -> Schedule | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if row is None or (row["status"] == "cancelled" and not include_cancelled):
                return None
            if row["status"] == "cancelled":
                return None
            return self._schedule_from_row(connection, row)

    def get_record(self, schedule_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if row is None:
                return None
            record = self._row_metadata(row)
            if row["status"] != "cancelled":
                record["schedule"] = self._schedule_from_row(connection, row)
            return record

    def assert_current_base(self, base_schedule_id: str, base_version: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            base = connection.execute(
                "SELECT * FROM schedules WHERE schedule_id = ? AND status = 'confirmed'",
                (base_schedule_id,),
            ).fetchone()
            if base is None:
                raise ScheduleNotFoundError(base_schedule_id)
            current = self._current_confirmed_row(connection, base["week_start"])
            current_version = current["version"] if current else None
            if (
                base["version"] != base_version
                or current is None
                or current["schedule_id"] != base_schedule_id
                or current_version != base_version
            ):
                raise VersionConflictError(current_version, base_version)
            record = self._row_metadata(base)
            record["schedule"] = self._schedule_from_row(connection, base)
            return record

    def confirm(self, schedule_id: str, version: int) -> Schedule:
        with self.database.transaction(immediate=True) as connection:
            draft = connection.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if draft is None or draft["status"] != "draft":
                raise DraftNotFoundError(schedule_id)
            if draft["version"] != version:
                raise VersionConflictError(draft["version"], version)
            validation = json.loads(draft["validation_json"])
            if not bool(validation.get("passed", validation.get("valid", False))):
                raise InvalidScheduleStateError("Only a valid draft can be confirmed")

            self._assert_current_week_base(
                connection,
                week_start=draft["week_start"],
                base_schedule_id=draft["base_schedule_id"],
                base_version=draft["base_version"],
            )
            metadata = json.loads(draft["metadata_json"])
            self._assert_history_dependency(
                connection,
                week_start=draft["week_start"],
                metadata=metadata,
            )
            self._assert_expected_employee_revision(
                connection, metadata.get("employee_revision")
            )

            following_week = date.fromisoformat(draft["week_start"]) + timedelta(days=7)
            dependent = self._current_confirmed_row(connection, following_week)
            if dependent is not None:
                raise InvalidScheduleStateError(
                    "A following-week schedule is already confirmed; replan it before changing this week"
                )

            connection.execute(
                """
                UPDATE schedules SET status = 'confirmed', confirmed_at = ?
                WHERE schedule_id = ?
                """,
                (utc_now(), schedule_id),
            )
            confirmed = connection.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            return self._schedule_from_row(connection, confirmed)

    def cancel(self, schedule_id: str, version: int) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            draft = connection.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if draft is None or draft["status"] != "draft":
                raise DraftNotFoundError(schedule_id)
            if draft["version"] != version:
                raise VersionConflictError(draft["version"], version)
            connection.execute(
                """
                UPDATE schedules SET status = 'cancelled', cancelled_at = ?
                WHERE schedule_id = ?
                """,
                (utc_now(), schedule_id),
            )
            return {
                "schedule_id": schedule_id,
                "version": version,
                "status": "cancelled",
                "base_schedule_id": draft["base_schedule_id"],
            }

    def versions(self, schedule_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            source = connection.execute(
                "SELECT lineage_id FROM schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if source is None:
                raise ScheduleNotFoundError(schedule_id)
            rows = connection.execute(
                """
                SELECT * FROM schedules WHERE lineage_id = ?
                ORDER BY version DESC, created_at DESC
                """,
                (source["lineage_id"],),
            ).fetchall()
            return [self._row_metadata(row) for row in rows]

    def latest(
        self, *, status: str = "confirmed", week_start: date | None = None
    ) -> Schedule | None:
        clauses = ["status = ?"]
        params: list[Any] = [status]
        if week_start is not None:
            clauses.append("week_start = ?")
            params.append(week_start.isoformat())
        with self.database.connect() as connection:
            if status == "confirmed":
                ordering = (
                    "week_start DESC, confirmed_at DESC, created_at DESC, schedule_id DESC"
                )
            else:
                ordering = "week_start DESC, version DESC, created_at DESC"
            row = connection.execute(
                f"""
                SELECT * FROM schedules WHERE {' AND '.join(clauses)}
                ORDER BY {ordering} LIMIT 1
                """,
                params,
            ).fetchone()
            return self._schedule_from_row(connection, row) if row else None

    def confirmed_for_week(self, week_start: date) -> Schedule | None:
        return self.latest(status="confirmed", week_start=week_start)

    def current_confirmed_record_for_week(self, week_start: date) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = self._current_confirmed_row(connection, week_start)
            if row is None:
                return None
            record = self._row_metadata(row)
            record["schedule"] = self._schedule_from_row(connection, row)
            return record

    def previous_week_context(
        self,
        week_start: date,
        *,
        allow_bootstrap: bool = False,
        allow_ephemeral_known_empty: bool = False,
    ) -> tuple[Schedule | None, HistoryStatus]:
        """Read preceding history and persist the sole explicitly empty anchor."""
        previous_week = week_start.fromordinal(week_start.toordinal() - 7)
        with self.database.transaction(immediate=True) as connection:
            previous = self._current_confirmed_row(connection, previous_week)
            if previous is not None:
                return self._schedule_from_row(connection, previous), HistoryStatus.AVAILABLE

            anchor = connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'initial_known_empty_week'"
            ).fetchone()
            if anchor is None and allow_bootstrap:
                schedule_exists = connection.execute(
                    "SELECT 1 FROM schedules LIMIT 1"
                ).fetchone()
                if schedule_exists is None:
                    connection.execute(
                        """
                        INSERT INTO system_metadata (key, value)
                        VALUES ('initial_known_empty_week', ?)
                        """,
                        (week_start.isoformat(),),
                    )
                    anchor_week = week_start.isoformat()
                else:
                    anchor_week = None
            elif anchor is not None:
                anchor_week = anchor["value"]
            else:
                anchor_week = None

            if (
                anchor is None
                and not allow_bootstrap
                and allow_ephemeral_known_empty
            ):
                schedule_exists = connection.execute(
                    "SELECT 1 FROM schedules LIMIT 1"
                ).fetchone()
                if schedule_exists is None:
                    return None, HistoryStatus.KNOWN_EMPTY

            if anchor_week == week_start.isoformat():
                return None, HistoryStatus.KNOWN_EMPTY
            return None, HistoryStatus.UNAVAILABLE

    def has_confirmed_before(self, week_start: date) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM schedules WHERE status = 'confirmed' AND week_start < ? LIMIT 1",
                (week_start.isoformat(),),
            ).fetchone()
        return row is not None
