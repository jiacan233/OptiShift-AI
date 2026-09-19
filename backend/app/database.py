from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from .models.orm import Base, EmployeeRecord, SystemMetadataRecord


def utc_now() -> datetime:
    return datetime.now(UTC)


def _default_database_url() -> str:
    return "sqlite:///./data/optishift.db"


def _sqlite_url(path: Path) -> str:
    if str(path) == ":memory:":
        return "sqlite:///:memory:"
    return f"sqlite:///{path.resolve().as_posix()}"


def _configured_database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env == "production" and not configured:
        raise RuntimeError("DATABASE_URL is required when APP_ENV=production")
    database_url = configured or _default_database_url()
    if "://" not in database_url:
        database_url = _sqlite_url(Path(database_url))
    driver = make_url(database_url).drivername
    if app_env == "production" and driver != "mysql+pymysql":
        raise RuntimeError(
            "Production requires a mysql+pymysql DATABASE_URL; SQLite fallback is disabled"
        )
    return database_url


class Database:
    """SQLAlchemy database boundary shared by SQLite and MySQL."""

    def __init__(self, value: Path | str | None = None) -> None:
        self._database_url = (
            self._coerce_url(value) if value is not None else _configured_database_url()
        )
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @staticmethod
    def _coerce_url(value: Path | str) -> str:
        if isinstance(value, Path):
            return _sqlite_url(value)
        if "://" in value:
            return value
        return _sqlite_url(Path(value))

    @property
    def url(self) -> str:
        return self._database_url

    @property
    def path(self) -> Path:
        url = make_url(self._database_url)
        if not url.drivername.startswith("sqlite"):
            raise AttributeError("path is only available for SQLite databases")
        return Path(url.database or ":memory:")

    @path.setter
    def path(self, value: Path | str) -> None:
        self.configure(value)

    def configure(self, value: Path | str) -> None:
        self.dispose()
        self._database_url = self._coerce_url(value)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            url = make_url(self._database_url)
            options: dict = {"pool_pre_ping": True}
            if url.drivername.startswith("sqlite"):
                database = url.database
                if database and database != ":memory:":
                    Path(database).parent.mkdir(parents=True, exist_ok=True)
                options["connect_args"] = {"check_same_thread": False, "timeout": 10}
            else:
                options["pool_recycle"] = 1800
            self._engine = create_engine(self._database_url, **options)
            if url.drivername.startswith("sqlite"):
                event.listen(self._engine, "connect", self._configure_sqlite)
            self._session_factory = sessionmaker(
                bind=self._engine,
                autoflush=True,
                expire_on_commit=False,
            )
        return self._engine

    @staticmethod
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 10000")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    @property
    def dialect_name(self) -> str:
        return self.engine.dialect.name

    @contextmanager
    def session(self, *, immediate: bool = False) -> Iterator[Session]:
        _ = self.engine
        assert self._session_factory is not None
        session = self._session_factory()
        try:
            if immediate and self.dialect_name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    transaction = session

    def initialize(self) -> None:
        """Prepare local/test databases and validate migrated production databases."""
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        if app_env == "production":
            db_inspector = inspect(self.engine)
            tables = set(db_inspector.get_table_names())
            required = {
                "employees",
                "system_metadata",
                "schedules",
                "assignments",
                "conversations",
                "conversation_messages",
                "agent_tool_calls",
                "conversation_scenarios",
            }
            missing = sorted(required - tables)
            if missing:
                raise RuntimeError(
                    "Database migrations have not been applied; missing tables: "
                    + ", ".join(missing)
                )
            required_columns = {
                "schedules": {"compliance_status"},
                "conversations": {
                    "conversation_id",
                    "browser_workspace_id",
                    "summary",
                    "active_turn_message_id",
                    "active_turn_owner_token",
                    "active_turn_started_at",
                    "updated_at",
                },
                "conversation_messages": {
                    "message_id",
                    "conversation_id",
                    "sequence_number",
                    "client_message_id",
                    "metadata_json",
                },
                "agent_tool_calls": {
                    "tool_call_id",
                    "conversation_id",
                    "sequence_number",
                    "message_id",
                    "output_json",
                },
            }
            missing_columns = {
                table: sorted(
                    columns
                    - {item["name"] for item in db_inspector.get_columns(table)}
                )
                for table, columns in required_columns.items()
            }
            missing_columns = {
                table: columns
                for table, columns in missing_columns.items()
                if columns
            }
            if missing_columns:
                details = "; ".join(
                    f"{table}: {', '.join(columns)}"
                    for table, columns in sorted(missing_columns.items())
                )
                raise RuntimeError(
                    "Database migrations are incomplete; missing columns: " + details
                )
        else:
            Base.metadata.create_all(self.engine)

        with self.session(immediate=True) as session:
            revision = session.get(SystemMetadataRecord, "employee_revision")
            if revision is None:
                session.add(SystemMetadataRecord(key="employee_revision", value="0"))

    def is_healthy(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return connection.execute(text("SELECT 1")).scalar_one() == 1
        except Exception:
            return False

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._session_factory = None


CANONICAL_EMPLOYEE_FIXTURE_VERSION = 2
DEMO_EMPLOYEE_FIXTURE_VERSION = 2

DEMO_EMPLOYEES = [
    {
        "id": "E01",
        "role": "manager",
        "skills": ["manager", "beverage", "cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Wed"],
        "preferred_shift": "morning",
    },
    {
        "id": "E02",
        "role": "vice_manager",
        "skills": ["manager", "beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    {
        "id": "E03",
        "role": "shift_leader",
        "skills": ["manager", "beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "leave_days": [],
        "preferred_shift": None,
    },
    {
        "id": "E04",
        "role": "shift_leader",
        "skills": ["manager", "beverage", "inventory"],
        "available_days": ["Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    {
        "id": "E05",
        "role": "senior_clerk",
        "skills": ["manager", "beverage", "cashier"],
        "available_days": ["Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    {
        "id": "E06",
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Tue"],
        "preferred_shift": "morning",
    },
    {
        "id": "E07",
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    {
        "id": "E08",
        "role": "clerk",
        "skills": ["beverage", "cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "leave_days": [],
        "preferred_shift": None,
    },
    {
        "id": "E09",
        "role": "clerk",
        "skills": ["beverage"],
        "available_days": ["Mon", "Wed", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    {
        "id": "E10",
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    {
        "id": "E11",
        "role": "clerk",
        "skills": ["cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    {
        "id": "E12",
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    {
        "id": "E13",
        "role": "part_time",
        "skills": ["beverage"],
        "available_days": ["Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "morning",
    },
    {
        "id": "E14",
        "role": "part_time",
        "skills": ["beverage", "cashier"],
        "available_days": ["Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    {
        "id": "E15",
        "role": "part_time",
        "skills": ["cashier"],
        "available_days": ["Fri", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    {
        "id": "E16",
        "role": "part_time",
        "skills": ["beverage"],
        "available_days": ["Wed", "Thu", "Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    {
        "id": "E17",
        "role": "clerk",
        "skills": ["beverage", "cashier", "inventory"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Mon"],
        "preferred_shift": None,
    },
    {
        "id": "E18",
        "role": "clerk",
        "skills": ["beverage", "cashier"],
        "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "leave_days": [],
        "preferred_shift": "evening",
    },
    {
        "id": "E19",
        "role": "part_time",
        "skills": ["beverage", "cashier"],
        "available_days": ["Sat", "Sun"],
        "leave_days": [],
        "preferred_shift": None,
    },
    {
        "id": "E20",
        "role": "clerk",
        "skills": ["beverage", "inventory"],
        "available_days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "leave_days": ["Thu"],
        "preferred_shift": "morning",
    },
]


def seed_demo_employees(database: Database) -> int:
    """Sync demo employees using versioned master data migration."""
    timestamp = utc_now()
    with database.transaction(immediate=True) as session:
        fixture_record = session.get(SystemMetadataRecord, "demo_employee_fixture_version")
        current_version = (
            int(fixture_record.value)
            if fixture_record is not None and fixture_record.value.isdigit()
            else 0
        )
        if current_version >= DEMO_EMPLOYEE_FIXTURE_VERSION:
            return 0

        existing = {
            emp.id: emp for emp in session.scalars(select(EmployeeRecord)).all()
        }
        mutated = False
        count = 0
        for item in DEMO_EMPLOYEES:
            emp_id = item["id"]
            if emp_id in existing:
                rec = existing[emp_id]
                if (
                    rec.role != item["role"]
                    or rec.skills != item["skills"]
                    or rec.available_days != item["available_days"]
                    or rec.leave_days != item["leave_days"]
                    or rec.preferred_shift != item["preferred_shift"]
                ):
                    rec.role = item["role"]
                    rec.skills = list(item["skills"])
                    rec.available_days = list(item["available_days"])
                    rec.leave_days = list(item["leave_days"])
                    rec.preferred_shift = item["preferred_shift"]
                    rec.updated_at = timestamp
                    mutated = True
                    count += 1
            else:
                session.add(
                    EmployeeRecord(
                        id=emp_id,
                        role=item["role"],
                        skills=list(item["skills"]),
                        available_days=list(item["available_days"]),
                        leave_days=list(item["leave_days"]),
                        preferred_shift=item["preferred_shift"],
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                mutated = True
                count += 1

        if fixture_record is None:
            session.add(
                SystemMetadataRecord(
                    key="demo_employee_fixture_version",
                    value=str(DEMO_EMPLOYEE_FIXTURE_VERSION),
                )
            )
        else:
            fixture_record.value = str(DEMO_EMPLOYEE_FIXTURE_VERSION)

        if mutated:
            revision = session.get(SystemMetadataRecord, "employee_revision")
            if revision is None:
                session.add(SystemMetadataRecord(key="employee_revision", value="1"))
            else:
                revision.value = str(int(revision.value) + 1)

        return count


database = Database()


def initialize_database() -> None:
    database.initialize()
    seed_demo_employees(database)
