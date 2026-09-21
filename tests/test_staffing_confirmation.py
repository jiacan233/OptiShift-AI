"""Persisted R04 confirmation uses the real Force solver and validator."""
from uuid import uuid4

import pytest

from backend.app.models import RuleConfig, StaffingConstraint
from backend.app.models.dialogue import DialogueState, TurnCommand
from backend.app.repository.dialogue import DialogueRepository
from backend.app.services.dialogue_parser import grounding_error
from backend.app.services.dialogue_staffing import staffing_confirmation
from tests.read_fixtures import WEEK, database_snapshot, seed_read_fixture


WORKSPACE = "staffing-confirmation"
REQUEST = "周日怎么这么多人？8个人差不多就够了"


@pytest.fixture
def setup(database):
    service = seed_read_fixture(database)
    service.tools.scheduling.context_builder.rules.max_time_seconds = 2
    cid = service.create_conversation(WORKSPACE)["conversation_id"]
    return service, cid


def send(service, cid, text, **kw):
    return service.send_message(conversation_id=cid, browser_workspace_id=WORKSPACE,
        content=text, client_message_id=kw.pop("client_message_id", uuid4().hex),
        current_week_start=WEEK, **kw)


def request(semantic_reply, service, cid, **bounds):
    semantic_reply({"execution": "create_draft", "mutation_requested": True,
        "staffing_constraints": [{"scope": "DAY", "days": ["Sun"], **(bounds or {"target_count": 8})}]}, service=service)
    return send(service, cid, REQUEST)


def decide(semantic_reply, service, decision):
    semantic_reply(lambda user: {"pending_decision": decision,
        "pending_action_id": next(p["id"] for p in user["state"]["pending"] if p["kind"] == "force_staffing"),
        "mutation_requested": True, "execution": "create_draft" if decision == "confirm" else "none"}, service=service)


def test_low_request_persists_without_solving(setup, database, semantic_reply, monkeypatch):
    service, cid = setup
    before = database_snapshot(database, business_only=True)
    def forbidden(*args, **kwargs):
        pytest.fail("preflight must not call solver")
    monkeypatch.setattr(service.tools.scheduling.solver, "solve", forbidden)
    result = request(semantic_reply, service, cid)
    assert "至少需要12人" in result["assistant_message"]["content"]
    assert "违反R04" in result["assistant_message"]["content"]
    assert not result["schedule_result"] and not result["tool_calls"]
    persisted = DialogueRepository(database).get(cid, WEEK)
    assert len(persisted.pending) == 1 and persisted.pending[0].kind == "force_staffing"
    assert not persisted.staffing_constraints
    assert persisted.pending[0].staffing_constraints[0].max_count == 8
    assert {s.allowed_shortage for s in persisted.pending[0].requested_overrides} == {4}
    assert before == database_snapshot(database, business_only=True)


@pytest.mark.parametrize("text", ["确定", "确定，就按8个人", "继续"])
def test_confirm_generates_eight_and_keeps_r04_conflicts(setup, database, semantic_reply, text):
    service, cid = setup
    rules = service.tools.scheduling.context_builder.rules.model_dump()
    request(semantic_reply, service, cid)
    # New repository instance models restoring a conversation after refresh.
    assert DialogueRepository(database).get(cid, WEEK).pending
    decide(semantic_reply, service, "confirm")
    client_id = uuid4().hex
    result = send(service, cid, text, client_message_id=client_id)
    draft = result["schedule_result"]
    assert draft["status"] == "feasible"
    assert sum(a["day"] == "Sun" for a in draft["schedule"]["assignments"]) == 8
    assert draft["compliance_status"] == "authorized_violations"
    assert draft["validation"]["valid"] is False
    assert draft["authorized_violations"] and all(v["rule_id"] == "R04" for v in draft["authorized_violations"])
    assert "R04" in result["assistant_message"]["content"]
    assert "非标准合规" in result["assistant_message"]["content"]
    assert any(t["tool_name"] == "force_generate_schedule" for t in result["tool_calls"])
    assert not DialogueRepository(database).get(cid, WEEK).pending
    assert rules == service.tools.scheduling.context_builder.rules.model_dump()
    assert service.tools.get_current_schedule(target_week=WEEK)["confirmed"]["schedule_id"] == "sch_eval_v2"
    replay = send(service, cid, text, client_message_id=client_id)
    assert replay["schedule_result"]["schedule_id"] == draft["schedule_id"]


def test_cancel_preserves_business_state_and_cannot_replay_confirmation(setup, database, semantic_reply):
    service, cid = setup
    before = database_snapshot(database, business_only=True)
    request(semantic_reply, service, cid)
    pending_id = DialogueRepository(database).get(cid, WEEK).pending[0].id
    decide(semantic_reply, service, "cancel")
    result = send(service, cid, "取消")
    assert "已取消" in result["assistant_message"]["content"]
    assert not result["schedule_result"] and not result["tool_calls"]
    restored = DialogueRepository(database).get(cid, WEEK)
    assert not restored.pending and not restored.staffing_constraints
    assert before == database_snapshot(database, business_only=True)
    assert grounding_error(TurnCommand(pending_decision="confirm", pending_action_id=pending_id,
        execution="create_draft"), restored, service.employees.list())


def test_confirmation_rejects_changed_rules(setup, database, semantic_reply):
    service, cid = setup
    request(semantic_reply, service, cid)
    service.tools.scheduling.context_builder.rules.weekend_min_staff = 7
    decide(semantic_reply, service, "confirm")
    result = send(service, cid, "确定")
    assert "失效" in result["assistant_message"]["content"]
    assert not result["schedule_result"] and not result["tool_calls"]
    assert not DialogueRepository(database).get(cid, WEEK).pending


@pytest.mark.parametrize("bounds", [{"max_count": 8}, {"min_count": 8, "target_count": 8, "max_count": 8}])
def test_low_upper_bound_also_requires_confirmation(setup, semantic_reply, bounds):
    service, cid = setup
    result = request(semantic_reply, service, cid, **bounds)
    assert "至少需要12人" in result["assistant_message"]["content"]
    assert not result["schedule_result"]


def test_per_shift_request_cannot_hide_baseline_r04():
    constraint = StaffingConstraint(scope="SHIFT", days=["Sun"], shifts=["morning"],
        min_count=4, target_count=4, max_count=4)
    rules = RuleConfig(staffing_constraints=[constraint])
    assert rules.minimum_staff("Sun", "morning") == 6
    pending = staffing_confirmation([constraint], RuleConfig(), "m")
    assert "周日早班当前规则至少需要6人" in pending.prompt
    assert len(pending.requested_overrides) == 1
    assert pending.requested_overrides[0].allowed_shortage == 2


@pytest.mark.parametrize("constraint", [
    StaffingConstraint(scope="DAY", days=["Sun"], min_count=8),
    StaffingConstraint(scope="DAY", days=["Sun"], target_count=12),
])
def test_compatible_constraints_need_no_exception(constraint):
    assert staffing_confirmation([constraint], RuleConfig(), "m") is None


def test_confirmation_cannot_cross_week_or_invent_payload():
    assert grounding_error(TurnCommand(pending_decision="confirm", pending_action_id="missing",
        execution="create_draft"), DialogueState(), [])
