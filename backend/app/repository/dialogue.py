"""Short fenced transactions. Slow parsing and solving run outside this boundary."""
from datetime import date
from uuid import uuid4

from sqlalchemy import select

from ..database import utc_now
from ..models.dialogue import Condition, DialogueState
from ..models.domain import ScenarioPatch
from ..models.orm import ConversationDialogueRecord, ConversationMessageRecord, ConversationRecord, ConversationScenarioRecord
from ..models.scenario_changes import scenario_patches_to_schedule_changes
from .conversations import ConversationNotFoundError, ConversationRepository, MessageNotFoundError
from .scenarios import ScenarioRevisionConflict


def patches_for(conditions):
    return [ScenarioPatch(employee_id=c.employee_id, change_type=c.type, days=[c.day], shift=c.shift)
            for condition in conditions for c in condition.changes]


def _constraint_keys(patches):
    """Compare effective atoms, not legacy grouping, JSON defaults or order."""
    return {
        (change.employee_id, change.type, change.day, change.shift)
        for change in scenario_patches_to_schedule_changes(
            [ScenarioPatch.model_validate(patch) for patch in patches]
        )
    }


class DialogueRepository:
    def __init__(self, database):
        self.database = database

    def get(self, conversation_id: str, week: date):
        with self.database.transaction() as session:
            row = session.get(ConversationDialogueRecord, (conversation_id, week))
            if row:
                return DialogueState.model_validate(row.payload)
            old = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week))
            state = DialogueState(scenario_revision=old.revision if old else 0)
            if old:
                # Import explicit fields only, never infer old clarification prose.
                for index, raw in enumerate(old.temporary_constraints or []):
                    patch = ScenarioPatch.model_validate(raw)
                    item = Condition(id=f"legacy_{old.scenario_id}_{index}",
                                     changes=scenario_patches_to_schedule_changes([patch]),
                                     source_message_id="legacy", source_kind="legacy")
                    state.conditions.append(item)
                state.context_ids = [item.id for item in state.conditions]
            return state

    def commit(self, conversation_id, workspace, week, state, *, expected_revision,
               message_id, owner_token, command, result=None):
        # Never mutate the caller's snapshot if the transaction is rolled back.
        state = state.model_copy(deep=True)
        with self.database.transaction(immediate=True) as session:
            conversation = session.scalar(select(ConversationRecord).where(
                ConversationRecord.conversation_id == conversation_id,
                ConversationRecord.browser_workspace_id == workspace).with_for_update())
            if not conversation:
                raise ConversationNotFoundError(conversation_id)
            ConversationRepository._require_turn_owner(conversation, message_id, owner_token)
            message = session.get(ConversationMessageRecord, message_id)
            if not message or message.conversation_id != conversation_id or message.role != "user":
                raise MessageNotFoundError(message_id)
            receipt = (message.metadata_json or {}).get("dialogue_commit")
            if receipt:
                if receipt["week"] != week.isoformat() or receipt["command"] != command:
                    raise ScenarioRevisionConflict("本轮已按其他目标周或指令提交，不能重复应用。")
                # The first commit records the reduced state before slow work;
                # a second call with ``result`` is the fenced writeback.  Once
                # a result exists this is an idempotent replay.
                if result is None or receipt.get("result") is not None:
                    return DialogueState.model_validate(receipt["state"])
            row = session.scalar(select(ConversationDialogueRecord).where(
                ConversationDialogueRecord.conversation_id == conversation_id,
                ConversationDialogueRecord.week_start == week).with_for_update())
            actual = row.revision if row else 0
            if actual != expected_revision:
                raise ScenarioRevisionConflict("对话状态已更新，请重新发起本轮操作。")
            scenario = session.scalar(select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation_id,
                ConversationScenarioRecord.week_start == week).with_for_update())
            if (scenario.revision if scenario else 0) != state.scenario_revision:
                raise ScenarioRevisionConflict("临时条件已更新，请重新读取。")
            patches = [p.model_dump(mode="json") for p in patches_for(state.conditions)]
            previous = scenario.temporary_constraints or [] if scenario else []
            changed = (_constraint_keys(patches) != _constraint_keys(previous) or
                (row.payload.get("staffing_constraints", []) if row else []) != [c.model_dump(mode="json") for c in state.staffing_constraints])
            if receipt and changed:
                # Result persistence must refer to the already committed command,
                # never silently introduce conditions after the Solver snapshot.
                raise ScenarioRevisionConflict("执行结果与已提交条件不一致，请重新发起。")
            if changed and not scenario:
                scenario = ConversationScenarioRecord(scenario_id=f"scn_{uuid4().hex[:12]}",
                    conversation_id=conversation_id, week_start=week, revision=0,
                    temporary_constraints=[], updated_at=utc_now())
                session.add(scenario)
            if changed:
                scenario.temporary_constraints = patches
                scenario.revision += 1
                scenario.last_preview_result = None
                scenario.last_strict_result = None
                scenario.updated_at = utc_now()
            state.scenario_revision = scenario.revision if scenario else 0
            # A result is attached to the command revision used during solving.
            # Replays and response recovery must not create another revision.
            state.revision = actual if receipt else actual + 1
            if not row:
                row = ConversationDialogueRecord(conversation_id=conversation_id, week_start=week)
                session.add(row)
            row.revision = state.revision
            row.payload = state.model_dump(mode="json")
            row.updated_at = utc_now()
            receipt = {"week": week.isoformat(), "state": row.payload, "command": command,
                       "result": result if result is not None else (receipt or {}).get("result")}
            message.metadata_json = {**(message.metadata_json or {}), "dialogue_commit": receipt}
            return state
