from __future__ import annotations

from datetime import date
from uuid import uuid4
from typing import Any

from sqlalchemy import select

from ..database import Database, utc_now
from ..models import ScenarioPatch, ScenarioState
from ..models.orm import ConversationScenarioRecord


class ScenarioRevisionConflict(RuntimeError):
    pass


class ScenarioRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _state(record: ConversationScenarioRecord) -> ScenarioState:
        return ScenarioState(
            conversation_id=record.conversation_id,
            week_start=record.week_start,
            revision=record.revision,
            patches=[ScenarioPatch.model_validate(item) for item in (record.temporary_constraints or [])],
            updated_at=record.updated_at,
        )

    def get(self, conversation_id: str, week_start: date) -> ScenarioState | None:
        with self.database.transaction() as session:
            record = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week_start,
            ))
            return self._state(record) if record else None

    def upsert_patch(
        self,
        conversation_id: str,
        week_start: date,
        patch: ScenarioPatch,
        *,
        expected_revision: int | None = None,
    ) -> ScenarioState:
        with self.database.transaction(immediate=True) as session:
            record = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week_start,
            ))
            if record is None:
                record = ConversationScenarioRecord(
                    scenario_id=f"scn_{uuid4().hex[:12]}",
                    conversation_id=conversation_id,
                    week_start=week_start,
                    revision=0,
                    temporary_constraints=[],
                    updated_at=utc_now(),
                )
                session.add(record)
                session.flush()
            if expected_revision is not None and record.revision != expected_revision:
                raise ScenarioRevisionConflict(
                    f"Scenario revision conflict: current={record.revision}, expected={expected_revision}"
                )
            patches = [ScenarioPatch.model_validate(item) for item in (record.temporary_constraints or [])]
            if patch.operation.value == "clear":
                patches = [item for item in patches if item.employee_id != patch.employee_id]
            else:
                existing = next((item for item in patches if item.employee_id == patch.employee_id and item.change_type == patch.change_type), None)
                current_days = list(existing.days) if existing else []
                if patch.operation.value == "set":
                    days = list(patch.days)
                elif patch.operation.value == "remove":
                    days = [day for day in current_days if day not in patch.days]
                else:
                    days = list(dict.fromkeys(current_days + list(patch.days)))
                patches = [item for item in patches if item is not existing]
                if days:
                    patches.append(patch.model_copy(update={"days": days}))
            record.temporary_constraints = [item.model_dump(mode="json") for item in patches]
            record.revision += 1
            record.updated_at = utc_now()
            session.flush()
            return self._state(record)

    def save_results(
        self,
        conversation_id: str,
        week_start: date,
        *,
        strict_result: dict[str, Any] | None = None,
        preview_result: dict[str, Any] | None = None,
    ) -> None:
        with self.database.transaction(immediate=True) as session:
            record = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week_start,
            ))
            if record is None:
                return
            if strict_result is not None:
                record.last_strict_result = strict_result
            if preview_result is not None:
                record.last_preview_result = preview_result
            record.updated_at = utc_now()
