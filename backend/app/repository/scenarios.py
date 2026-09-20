from __future__ import annotations

from datetime import date
from uuid import uuid4
from typing import Any

from sqlalchemy import select
from pydantic import ValidationError

from ..database import Database, utc_now
from ..models import ScenarioPatch, ScenarioState
from ..models.scenario_changes import apply_scenario_patch, apply_scenario_patches
from ..models.orm import ConversationScenarioRecord, ConversationRecord, ConversationDialogueRecord
from .conversations import ConversationBusyError, ConversationNotFoundError


class ScenarioRevisionConflict(RuntimeError):
    pass


class ScenarioInvalidatedError(RuntimeError):
    pass


class ScenarioRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def clear(self, conversation_id: str, browser_workspace_id: str, week_start: date,
              expected_revision: int | None = None) -> None:
        with self.database.transaction(immediate=True) as session:
            conversation = session.scalar(select(ConversationRecord).where(
                ConversationRecord.conversation_id == conversation_id,
                ConversationRecord.browser_workspace_id == browser_workspace_id,
            ).with_for_update())
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            if conversation.active_turn_message_id:
                raise ConversationBusyError(conversation_id)
            record = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week_start,
            ).with_for_update())
            if record and (record.temporary_constraints or record.last_preview_result or record.last_strict_result):
                if expected_revision is not None and record.revision != expected_revision:
                    raise ScenarioRevisionConflict()
                record.temporary_constraints = []
                record.last_preview_result = None
                record.last_strict_result = None
                record.revision += 1
                record.updated_at = utc_now()
            conversation.summary = None
            dialogue = session.get(ConversationDialogueRecord, (conversation_id, week_start))
            if dialogue:
                from ..models.dialogue import DialogueState
                dialogue.revision += 1
                dialogue.payload = DialogueState(
                    revision=dialogue.revision, scenario_revision=record.revision if record else 0,
                ).model_dump(mode="json")
                dialogue.updated_at = utc_now()

    @staticmethod
    def _state(record: ConversationScenarioRecord) -> ScenarioState:
        try:
            patches = [ScenarioPatch.model_validate(item) for item in (record.temporary_constraints or [])]
        except ValidationError:
            # Invalidate only this temporary scenario, never guess a missing shift.
            patches = []
            record.temporary_constraints = []
            record.last_preview_result = None
            record.last_strict_result = {"invalidated": True}
            record.revision += 1
            record.updated_at = utc_now()
        invalidated = bool((record.last_strict_result or {}).get("invalidated"))
        return ScenarioState(
            conversation_id=record.conversation_id,
            week_start=record.week_start,
            revision=record.revision,
            patches=patches,
            updated_at=record.updated_at,
            invalidated=invalidated,
            message="旧试排条件已失效，请重新发起本次试排。" if invalidated else None,
        )

    def get(self, conversation_id: str, week_start: date) -> ScenarioState | None:
        with self.database.transaction(immediate=True) as session:
            record = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week_start,
            ).with_for_update())
            return self._state(record) if record else None

    def invalidated_states(self, conversation_id: str) -> list[ScenarioState]:
        with self.database.transaction(immediate=True) as session:
            records = session.scalars(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
            ).with_for_update()).all()
            return [state for record in records if (state := self._state(record)).invalidated]

    def get_preview_result(self, conversation_id: str, week_start: date) -> dict[str, Any] | None:
        state = self.get(conversation_id, week_start)
        if state and state.invalidated:
            raise ScenarioInvalidatedError()
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

    _apply_patch = staticmethod(apply_scenario_patch)

    def upsert_patches(
        self,
        conversation_id: str,
        week_start: date,
        patches: list[ScenarioPatch],
        *,
        expected_revision: int | None = None,
    ) -> ScenarioState:
        """Apply a complete change batch against one revision atomically."""
        self.get(conversation_id, week_start)
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
            current = apply_scenario_patches(current, incoming)
            patches = current
            record.temporary_constraints = [item.model_dump(mode="json") for item in patches]
            record.last_strict_result = None
            record.last_preview_result = None
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
