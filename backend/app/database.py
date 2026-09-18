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


DEMO_EMPLOYEES = [
    ("E01", "manager", ["manager", "beverage", "cashier", "inventory"], "morning", []),
    ("E02", "manager", ["manager", "cashier", "inventory"], "evening", ["Mon", "Tue", "Wed", "Thu", "Sat", "Sun"]),
    ("E03", "manager", ["manager", "beverage", "cashier"], "morning", ["Tue"]),
    ("E04", "manager", ["manager", "beverage", "inventory"], "evening", ["Wed", "Fri"]),
    ("E05", "full_time", ["beverage", "cashier"], "morning", ["Mon"]),
    ("E06", "full_time", ["beverage", "cashier"], "evening", ["Tue"]),
    ("E07", "full_time", ["beverage", "cashier"], "morning", ["Wed"]),
    ("E08", "full_time", ["beverage", "cashier"], "evening", ["Thu"]),
    ("E09", "full_time", ["beverage", "cashier"], "morning", ["Fri"]),
    ("E10", "full_time", ["beverage", "cashier"], "evening", ["Sat"]),
    ("E11", "part_time", ["beverage", "cashier"], "morning", ["Sun"]),
    ("E12", "part_time", ["beverage", "cashier"], "evening", ["Mon"]),
    ("E13", "part_time", ["beverage", "cashier"], "morning", []),
    ("E14", "part_time", ["beverage", "cashier"], "evening", ["Thu"]),
    ("E15", "part_time", ["beverage", "cashier"], "morning", []),
    ("E16", "part_time", ["beverage", "cashier"], "evening", ["Fri"]),
]


def seed_demo_employees(database: Database) -> int:
    """Insert missing demo employees without overwriting existing master data."""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    timestamp = utc_now()
    created = 0
    with database.transaction(immediate=True) as session:
        existing_ids = set(session.scalars(select(EmployeeRecord.id)).all())
        for employee_id, role, skills, preferred_shift, unavailable in DEMO_EMPLOYEES:
            if employee_id in existing_ids:
                continue
            session.add(
                EmployeeRecord(
                    id=employee_id,
                    role=role,
                    skills=skills,
                    available_days=[day for day in days if day not in unavailable],
                    leave_days=[],
                    preferred_shift=preferred_shift,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            created += 1
        if created:
            revision = session.get(SystemMetadataRecord, "employee_revision")
            if revision is None:
                session.add(SystemMetadataRecord(key="employee_revision", value="1"))
            else:
                revision.value = str(int(revision.value) + 1)
    return created


database = Database()


def initialize_database() -> None:
    database.initialize()
    seed_demo_employees(database)
