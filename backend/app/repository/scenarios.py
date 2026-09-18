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

    def get_preview_result(self, conversation_id: str, week_start: date) -> dict[str, Any] | None:
        with self.database.transaction() as session:
            record = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week_start,
            ))
            return dict(record.last_preview_result or {}) if record and record.last_preview_result else None

    def upsert_patch(
        self,
        conversation_id: str,
        week_start: date,
        patch: ScenarioPatch,
        *,
        expected_revision: int | None = None,
    ) -> ScenarioState:
        return self.upsert_patches(
            conversation_id,
            week_start,
            [patch],
            expected_revision=expected_revision,
        )

    @staticmethod
    def _apply_patch(
        patches: list[ScenarioPatch], patch: ScenarioPatch
    ) -> list[ScenarioPatch]:
        """Apply one operation to an in-memory snapshot."""
        operation = patch.operation.value
        affected = [item for item in patches if item.employee_id == patch.employee_id]
        if operation == "clear":
            if patch.days:
                remaining: list[ScenarioPatch] = []
                for item in patches:
                    if item.employee_id != patch.employee_id:
                        remaining.append(item)
                        continue
                    days = [day for day in item.days if day not in patch.days]
                    if days:
                        remaining.append(item.model_copy(update={"days": days}))
                return remaining
            return [item for item in patches if item.employee_id != patch.employee_id]

        same_type = next(
            (
                item
                for item in affected
                if item.change_type == patch.change_type
            ),
            None,
        )
        current_days = list(same_type.days) if same_type else []
        if operation == "set":
            days = list(dict.fromkeys(patch.days))
        elif operation == "remove":
            days = [day for day in current_days if day not in patch.days]
        else:
            days = list(dict.fromkeys(current_days + list(patch.days)))

        result = [item for item in patches if item is not same_type]
        if days:
            result.append(patch.model_copy(update={"operation": "add", "days": days}))
        return result

    def upsert_patches(
        self,
        conversation_id: str,
        week_start: date,
        patches: list[ScenarioPatch],
        *,
        expected_revision: int | None = None,
    ) -> ScenarioState:
        """Apply a complete change batch against one revision atomically."""
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
            # Validate and reduce the whole batch before touching the record.
            incoming = [ScenarioPatch.model_validate(item) for item in patches]
            current = [
                ScenarioPatch.model_validate(item)
                for item in (record.temporary_constraints or [])
            ]
            for patch in incoming:
                current = self._apply_patch(current, patch)
            patches = current
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
