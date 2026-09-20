from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from backend.app.database import Database, utc_now
from backend.app.models.dialogue import Condition, DialogueState
from backend.app.models.domain import ChangeType, Day, ScheduleChange, Shift
from backend.app.models.orm import ConversationScenarioRecord
from backend.app.repository.conversations import ConversationRepository
from backend.app.repository.dialogue import DialogueRepository
from backend.app.repository.scenarios import ScenarioRevisionConflict


WEEK = date(2026, 9, 21)
WORKSPACE = "repository-test-workspace"


def _condition(employee: str = "E18", day: Day = Day.THU) -> Condition:
    return Condition(
        id="condition-1",
        changes=[
            ScheduleChange(
                employee_id=employee,
                type=ChangeType.PREFERENCE,
                day=day,
                shift=Shift.EVENING,
            )
        ],
        source_message_id="message-1",
    )


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "dialogue.db")
    database.initialize()
    return database


def _turn(database: Database, conversation_id: str, client_id: str = "turn-1"):
    conversations = ConversationRepository(database)
    user, created, owner = conversations.add_user_message(
        conversation_id,
        WORKSPACE,
        client_message_id=client_id,
        content="只记录条件",
        target_week=WEEK,
    )
    assert created and owner
    return conversations, user, owner


def test_read_only_focus_commit_does_not_create_scenario(tmp_path) -> None:
    database = _database(tmp_path)
    conversations = ConversationRepository(database)
    conversation = conversations.create_conversation(WORKSPACE)["conversation_id"]
    _, user, owner = _turn(database, conversation)

    repository = DialogueRepository(database)
    state = repository.get(conversation, WEEK)
    committed = repository.commit(
        conversation,
        WORKSPACE,
        WEEK,
        state,
        expected_revision=0,
        message_id=user["message_id"],
        owner_token=owner,
        command={"execution": "none", "source": "read_focus"},
    )

    assert committed.revision == 1
    with database.transaction() as session:
        assert session.scalar(
            select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation,
                ConversationScenarioRecord.week_start == WEEK,
            )
        ) is None


def test_proposal_only_commit_does_not_create_scenario(tmp_path) -> None:
    database = _database(tmp_path)
    conversations = ConversationRepository(database)
    conversation = conversations.create_conversation(WORKSPACE)["conversation_id"]
    _, user, owner = _turn(database, conversation)
    repository = DialogueRepository(database)
    state = DialogueState(proposals=[_condition()])

    committed = repository.commit(
        conversation,
        WORKSPACE,
        WEEK,
        state,
        expected_revision=0,
        message_id=user["message_id"],
        owner_token=owner,
        command={"execution": "analyze", "source": "proposal_only"},
    )

    assert committed.proposals
    with database.transaction() as session:
        assert session.scalar(
            select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation,
                ConversationScenarioRecord.week_start == WEEK,
            )
        ) is None


def test_legacy_import_and_new_condition_compare_semantically(tmp_path) -> None:
    database = _database(tmp_path)
    conversations = ConversationRepository(database)
    conversation = conversations.create_conversation(WORKSPACE)["conversation_id"]
    legacy = {
        "employee_id": "E18",
        "change_type": "preference",
        "days": ["Thu"],
        "shift": "evening",
        "operation": "add",
    }
    with database.transaction(immediate=True) as session:
        session.add(
            ConversationScenarioRecord(
                scenario_id="legacy-scenario",
                conversation_id=conversation,
                week_start=WEEK,
                revision=3,
                temporary_constraints=[legacy],
                updated_at=utc_now(),
            )
        )

    repository = DialogueRepository(database)
    state = repository.get(conversation, WEEK)
    assert state.scenario_revision == 3
    assert state.conditions[0].changes[0].employee_id == "E18"
    assert state.conditions[0].changes[0].day == Day.THU

    _, user, owner = _turn(database, conversation)
    committed = repository.commit(
        conversation,
        WORKSPACE,
        WEEK,
        state,
        expected_revision=0,
        message_id=user["message_id"],
        owner_token=owner,
        command={"execution": "none", "source": "legacy_import"},
    )
    assert committed.scenario_revision == 3
    with database.transaction() as session:
        row = session.get(ConversationScenarioRecord, "legacy-scenario")
        assert row.revision == 3
        assert row.temporary_constraints == [legacy]


def test_stale_revision_does_not_create_or_mutate_rows(tmp_path) -> None:
    database = _database(tmp_path)
    conversations = ConversationRepository(database)
    conversation = conversations.create_conversation(WORKSPACE)["conversation_id"]
    _, user, owner = _turn(database, conversation)
    repository = DialogueRepository(database)
    state = DialogueState(conditions=[_condition()])

    with pytest.raises(ScenarioRevisionConflict):
        repository.commit(
            conversation,
            WORKSPACE,
            WEEK,
            state,
            expected_revision=1,
            message_id=user["message_id"],
            owner_token=owner,
            command={"execution": "none", "source": "stale"},
        )

    assert repository.get(conversation, WEEK).revision == 0
    with database.transaction() as session:
        assert session.scalar(
            select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == conversation,
                ConversationScenarioRecord.week_start == WEEK,
            )
        ) is None
