from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _database_path() -> Path:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        if configured.startswith("sqlite:///"):
            configured = configured.removeprefix("sqlite:///")
        elif configured.startswith("sqlite://"):
            configured = configured.removeprefix("sqlite://")
        if configured == ":memory:":
            return Path(":memory:")
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = Path.cwd() / path
            return path.resolve()
    return (Path.cwd() / "data" / "optishift.db").resolve()


class Database:
    """Small SQLite lifecycle wrapper with one connection per operation."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _database_path()

    def connect(self) -> sqlite3.Connection:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self.path), timeout=10, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction(immediate=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    skills_json TEXT NOT NULL,
                    available_days_json TEXT NOT NULL,
                    leave_days_json TEXT NOT NULL,
                    preferred_shift TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO system_metadata (key, value)
                    VALUES ('employee_revision', '0');

                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    lineage_id TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version > 0),
                    parent_schedule_id TEXT,
                    base_schedule_id TEXT,
                    base_version INTEGER,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'confirmed', 'cancelled')),
                    week_start TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    cancelled_at TEXT,
                    FOREIGN KEY(parent_schedule_id) REFERENCES schedules(schedule_id),
                    FOREIGN KEY(base_schedule_id) REFERENCES schedules(schedule_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS uq_confirmed_lineage_version
                    ON schedules(lineage_id, version)
                    WHERE status = 'confirmed';
                CREATE INDEX IF NOT EXISTS idx_schedules_lineage_version
                    ON schedules(lineage_id, version DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_schedules_week_status
                    ON schedules(week_start, status, version DESC);

                CREATE TABLE IF NOT EXISTS assignments (
                    schedule_id TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    shift TEXT NOT NULL,
                    PRIMARY KEY(schedule_id, employee_id, day, shift),
                    FOREIGN KEY(schedule_id) REFERENCES schedules(schedule_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_assignments_schedule
                    ON assignments(schedule_id, day, shift);
                """
            )

    def is_healthy(self) -> bool:
        try:
            with self.connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False


DEMO_EMPLOYEES = [
    # id, role, verified skills, preferred shift, deterministic unavailable days
    ("E01", "manager", ["manager", "beverage", "cashier", "inventory"], "morning", []),
    # E02 is a Friday-only relief manager so the leave/replan demo causes a real replacement.
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


def seed_demo_employees(database: Database) -> None:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    timestamp = utc_now()
    with database.transaction(immediate=True) as connection:
        count = connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        if count:
            return
        connection.executemany(
            """
            INSERT INTO employees (
                id, role, skills_json, available_days_json, leave_days_json,
                preferred_shift, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    employee_id,
                    role,
                    json.dumps(skills),
                    json.dumps(available_days),
                    "[]",
                    preferred_shift,
                    timestamp,
                    timestamp,
                )
                for employee_id, role, skills, preferred_shift, unavailable in DEMO_EMPLOYEES
                for available_days in [[day for day in days if day not in unavailable]]
            ],
        )
        connection.execute(
            """
            UPDATE system_metadata
            SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            WHERE key = 'employee_revision'
            """
        )


database = Database()


def initialize_database() -> None:
    database.initialize()
    seed_demo_employees(database)
