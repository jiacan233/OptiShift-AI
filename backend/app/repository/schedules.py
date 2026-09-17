from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import Database, utc_now
from ..models import Assignment, HistoryStatus, Schedule
from ..models.orm import (
    AssignmentRecord,
    ScheduleRecord,
    SystemMetadataRecord,
)


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
    def _as_date(value: date | str) -> date:
        return value if isinstance(value, date) else date.fromisoformat(value)

    @staticmethod
    def _load_assignments(session: Session, schedule_id: str) -> list[Assignment]:
        records = session.scalars(
            select(AssignmentRecord)
            .where(AssignmentRecord.schedule_id == schedule_id)
            .order_by(
                AssignmentRecord.day,
                AssignmentRecord.shift,
                AssignmentRecord.employee_id,
            )
        ).all()
        return [
            Assignment(
                employee_id=record.employee_id,
                day=record.day,
                shift=record.shift,
            )
            for record in records
        ]

    @classmethod
    def _schedule_from_record(cls, session: Session, record: ScheduleRecord) -> Schedule:
        return Schedule(
            schedule_id=record.schedule_id,
            version=record.version,
            parent_schedule_id=record.parent_schedule_id,
            status=record.status,
            week_start=record.week_start,
            assignments=cls._load_assignments(session, record.schedule_id),
            created_at=record.created_at,
        )

    @staticmethod
    def _record_metadata(record: ScheduleRecord) -> dict[str, Any]:
        return {
            "schedule_id": record.schedule_id,
            "lineage_id": record.lineage_id,
            "version": record.version,
            "parent_schedule_id": record.parent_schedule_id,
            "base_schedule_id": record.base_schedule_id,
            "base_version": record.base_version,
            "status": record.status,
            "week_start": record.week_start.isoformat(),
            "validation": dict(record.validation_json),
            "metadata": dict(record.metadata_json),
            "created_at": record.created_at.isoformat(),
            "confirmed_at": (
                record.confirmed_at.isoformat() if record.confirmed_at else None
            ),
            "cancelled_at": (
                record.cancelled_at.isoformat() if record.cancelled_at else None
            ),
        }

    @staticmethod
    def _lock(statement, session: Session):
        if session.bind is not None and session.bind.dialect.name != "sqlite":
            return statement.with_for_update()
        return statement

    @classmethod
    def _current_confirmed_record(
        cls,
        session: Session,
        week_start: date | str,
        *,
        lock: bool = False,
    ) -> ScheduleRecord | None:
        statement = (
            select(ScheduleRecord)
            .where(
                ScheduleRecord.week_start == cls._as_date(week_start),
                ScheduleRecord.status == "confirmed",
            )
            .order_by(
                ScheduleRecord.version.desc(),
                ScheduleRecord.confirmed_at.desc(),
                ScheduleRecord.created_at.desc(),
                ScheduleRecord.schedule_id.desc(),
            )
            .limit(1)
        )
        if lock:
            statement = cls._lock(statement, session)
        return session.scalar(statement)

    @classmethod
    def _employee_revision(cls, session: Session, *, lock: bool = False) -> int:
        statement = select(SystemMetadataRecord).where(
            SystemMetadataRecord.key == "employee_revision"
        )
        if lock:
            statement = cls._lock(statement, session)
        record = session.scalar(statement)
        return int(record.value) if record is not None else 0

    @classmethod
    def _assert_expected_employee_revision(
        cls,
        session: Session,
        expected_revision: int | None,
    ) -> None:
        if expected_revision is None:
            return
        if cls._employee_revision(session, lock=True) != expected_revision:
            raise InvalidScheduleStateError(
                "Employee master data changed while the schedule was being prepared"
            )

    @classmethod
    def _assert_current_week_base(
        cls,
        session: Session,
        *,
        week_start: date | str,
        base_schedule_id: str | None,
        base_version: int | None,
    ) -> ScheduleRecord | None:
        current = cls._current_confirmed_record(
            session, week_start, lock=True
        )
        current_version = current.version if current is not None else None
        if base_schedule_id is None:
            if current is not None:
                raise VersionConflictError(current_version, None)
            return None
        if (
            current is None
            or current.schedule_id != base_schedule_id
            or current.version != base_version
        ):
            raise VersionConflictError(current_version, base_version)
        return current

    @classmethod
    def _assert_history_dependency(
        cls,
        session: Session,
        *,
        week_start: date | str,
        metadata: dict[str, Any],
    ) -> None:
        week = cls._as_date(week_start)
        expected_id = metadata.get("history_schedule_id")
        expected_version = metadata.get("history_schedule_version")
        current = cls._current_confirmed_record(
            session, week - timedelta(days=7), lock=True
        )
        if expected_id is not None:
            current_id = current.schedule_id if current is not None else None
            current_version = current.version if current is not None else None
            if current_id != expected_id or current_version != expected_version:
                raise VersionConflictError(current_version, expected_version)
            return

        if metadata.get("history_status") == HistoryStatus.KNOWN_EMPTY.value:
            anchor = session.get(SystemMetadataRecord, "initial_known_empty_week")
            if current is not None or anchor is None or anchor.value != week.isoformat():
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

        with self.database.transaction(immediate=True) as session:
            current = self._assert_current_week_base(
                session,
                week_start=schedule.week_start,
                base_schedule_id=base_schedule_id,
                base_version=base_version,
            )
            if current is not None and (
                current.lineage_id != lineage_id
                or schedule.parent_schedule_id != base_schedule_id
                or schedule.version != (base_version or 0) + 1
            ):
                raise VersionConflictError(current.version, base_version)
            if current is None and (
                base_schedule_id is not None
                or base_version is not None
                or schedule.parent_schedule_id is not None
                or schedule.version != 1
            ):
                raise VersionConflictError(None, base_version)
            self._assert_expected_employee_revision(session, employee_revision)
            self._assert_history_dependency(
                session,
                week_start=schedule.week_start,
                metadata=metadata_payload,
            )

            schedule_record = ScheduleRecord(
                    schedule_id=schedule.schedule_id,
                    lineage_id=lineage_id,
                    version=schedule.version,
                    parent_schedule_id=schedule.parent_schedule_id,
                    base_schedule_id=base_schedule_id,
                    base_version=base_version,
                    status="draft",
                    week_start=schedule.week_start,
                    validation_json=validation,
                    metadata_json=metadata_payload,
                    created_at=schedule.created_at,
                )
            session.add(schedule_record)
            # AssignmentRecord does not expose an ORM relationship to ScheduleRecord.
            # Flush the parent explicitly so foreign-key checks are deterministic on
            # both SQLite and MySQL.
            session.flush()
            session.add_all(
                [
                    AssignmentRecord(
                        schedule_id=schedule.schedule_id,
                        employee_id=assignment["employee_id"],
                        day=assignment["day"],
                        shift=assignment["shift"],
                    )
                    for assignment in payload["assignments"]
                ]
            )
        return schedule

    def get(self, schedule_id: str, *, include_cancelled: bool = False) -> Schedule | None:
        with self.database.transaction() as session:
            record = session.get(ScheduleRecord, schedule_id)
            if record is None or record.status == "cancelled":
                return None
            return self._schedule_from_record(session, record)

    def get_record(self, schedule_id: str) -> dict[str, Any] | None:
        with self.database.transaction() as session:
            record = session.get(ScheduleRecord, schedule_id)
            if record is None:
                return None
            result = self._record_metadata(record)
            if record.status != "cancelled":
                result["schedule"] = self._schedule_from_record(session, record)
            return result

    def assert_current_base(
        self, base_schedule_id: str, base_version: int
    ) -> dict[str, Any]:
        with self.database.transaction() as session:
            base = session.scalar(
                select(ScheduleRecord).where(
                    ScheduleRecord.schedule_id == base_schedule_id,
                    ScheduleRecord.status == "confirmed",
                )
            )
            if base is None:
                raise ScheduleNotFoundError(base_schedule_id)
            current = self._current_confirmed_record(session, base.week_start)
            current_version = current.version if current else None
            if (
                base.version != base_version
                or current is None
                or current.schedule_id != base_schedule_id
                or current_version != base_version
            ):
                raise VersionConflictError(current_version, base_version)
            record = self._record_metadata(base)
            record["schedule"] = self._schedule_from_record(session, base)
            return record

    def confirm(self, schedule_id: str, version: int) -> Schedule:
        with self.database.transaction(immediate=True) as session:
            statement = self._lock(
                select(ScheduleRecord).where(
                    ScheduleRecord.schedule_id == schedule_id
                ),
                session,
            )
            draft = session.scalar(statement)
            if draft is None or draft.status != "draft":
                raise DraftNotFoundError(schedule_id)
            if draft.version != version:
                raise VersionConflictError(draft.version, version)
            validation = draft.validation_json
            if not bool(validation.get("passed", validation.get("valid", False))):
                raise InvalidScheduleStateError("Only a valid draft can be confirmed")

            self._assert_current_week_base(
                session,
                week_start=draft.week_start,
                base_schedule_id=draft.base_schedule_id,
                base_version=draft.base_version,
            )
            self._assert_history_dependency(
                session,
                week_start=draft.week_start,
                metadata=draft.metadata_json,
            )
            self._assert_expected_employee_revision(
                session, draft.metadata_json.get("employee_revision")
            )

            dependent = self._current_confirmed_record(
                session, draft.week_start + timedelta(days=7), lock=True
            )
            if dependent is not None:
                raise InvalidScheduleStateError(
                    "A following-week schedule is already confirmed; replan it before changing this week"
                )

            draft.status = "confirmed"
            draft.confirmed_at = utc_now()
            session.flush()
            return self._schedule_from_record(session, draft)

    def cancel(self, schedule_id: str, version: int) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as session:
            statement = self._lock(
                select(ScheduleRecord).where(
                    ScheduleRecord.schedule_id == schedule_id
                ),
                session,
            )
            draft = session.scalar(statement)
            if draft is None or draft.status != "draft":
                raise DraftNotFoundError(schedule_id)
            if draft.version != version:
                raise VersionConflictError(draft.version, version)
            draft.status = "cancelled"
            draft.cancelled_at = utc_now()
            return {
                "schedule_id": schedule_id,
                "version": version,
                "status": "cancelled",
                "base_schedule_id": draft.base_schedule_id,
            }

    def versions(self, schedule_id: str) -> list[dict[str, Any]]:
        with self.database.transaction() as session:
            source = session.get(ScheduleRecord, schedule_id)
            if source is None:
                raise ScheduleNotFoundError(schedule_id)
            records = session.scalars(
                select(ScheduleRecord)
                .where(ScheduleRecord.lineage_id == source.lineage_id)
                .order_by(
                    ScheduleRecord.version.desc(), ScheduleRecord.created_at.desc()
                )
            ).all()
            return [self._record_metadata(record) for record in records]

    def latest(
        self, *, status: str = "confirmed", week_start: date | None = None
    ) -> Schedule | None:
        statement = select(ScheduleRecord).where(ScheduleRecord.status == status)
        if week_start is not None:
            statement = statement.where(ScheduleRecord.week_start == week_start)
        if status == "confirmed":
            statement = statement.order_by(
                ScheduleRecord.week_start.desc(),
                ScheduleRecord.version.desc(),
                ScheduleRecord.confirmed_at.desc(),
                ScheduleRecord.created_at.desc(),
                ScheduleRecord.schedule_id.desc(),
            )
        else:
            statement = statement.order_by(
                ScheduleRecord.week_start.desc(),
                ScheduleRecord.version.desc(),
                ScheduleRecord.created_at.desc(),
            )
        with self.database.transaction() as session:
            record = session.scalar(statement.limit(1))
            return self._schedule_from_record(session, record) if record else None

    def confirmed_for_week(self, week_start: date) -> Schedule | None:
        return self.latest(status="confirmed", week_start=week_start)

    def current_confirmed_record_for_week(
        self, week_start: date
    ) -> dict[str, Any] | None:
        with self.database.transaction() as session:
            record = self._current_confirmed_record(session, week_start)
            if record is None:
                return None
            result = self._record_metadata(record)
            result["schedule"] = self._schedule_from_record(session, record)
            return result

    def previous_week_context(
        self,
        week_start: date,
        *,
        allow_bootstrap: bool = False,
        allow_ephemeral_known_empty: bool = False,
    ) -> tuple[Schedule | None, HistoryStatus]:
        previous_week = week_start - timedelta(days=7)
        with self.database.transaction(immediate=True) as session:
            previous = self._current_confirmed_record(
                session, previous_week, lock=True
            )
            if previous is not None:
                return (
                    self._schedule_from_record(session, previous),
                    HistoryStatus.AVAILABLE,
                )

            anchor = session.get(SystemMetadataRecord, "initial_known_empty_week")
            if anchor is None and allow_bootstrap:
                schedule_exists = session.scalar(select(ScheduleRecord.schedule_id).limit(1))
                if schedule_exists is None:
                    anchor = SystemMetadataRecord(
                        key="initial_known_empty_week", value=week_start.isoformat()
                    )
                    session.add(anchor)

            if anchor is None and not allow_bootstrap and allow_ephemeral_known_empty:
                schedule_exists = session.scalar(select(ScheduleRecord.schedule_id).limit(1))
                if schedule_exists is None:
                    return None, HistoryStatus.KNOWN_EMPTY

            if anchor is not None and anchor.value == week_start.isoformat():
                return None, HistoryStatus.KNOWN_EMPTY
            return None, HistoryStatus.UNAVAILABLE

    def has_confirmed_before(self, week_start: date) -> bool:
        with self.database.transaction() as session:
            schedule_id = session.scalar(
                select(ScheduleRecord.schedule_id)
                .where(
                    ScheduleRecord.status == "confirmed",
                    ScheduleRecord.week_start < week_start,
                )
                .limit(1)
            )
            return schedule_id is not None
