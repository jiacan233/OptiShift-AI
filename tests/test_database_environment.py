from __future__ import annotations

from backend.app.database import Database


def test_temporary_database_ignores_production_dotenv(tmp_path) -> None:
    """A production value inherited before pytest must not disable test setup."""
    database = Database(tmp_path / "isolated.db")
    database.initialize()

    assert database.is_healthy()
