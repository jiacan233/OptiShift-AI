"""Unit and integration tests for flexible scheduling multi-turn state management.

Verifies:
Case 1: E10这周安排5天 -> Tue-Sun里随便5天，早晚随便 => Direct Draft
Case 2: E10周二到周六都上，班次你看着排 => Direct Draft
Case 3: E10这周上5天 -> Tue-Sun都安排，早晚随便 => Only ask 5-day vs 6-day conflict, then resolve
"""

from __future__ import annotations

import pytest

from tests.test_agent import WEEK_40, WORKSPACE, _conversation, _generate_and_confirm, _send
from tests.test_agent import agent_client as dialogue_api_client


FLEXIBLE_PLANS = {
    "E10这周安排5天": {
        "edits": [{
            "employee_ids": ["E10"],
            "type": "assign",
            "work_day_count": 5,
            "work_day_count_mode": "FIXED",
            "day_selection_mode": "UNKNOWN",
            "shift_mode": "UNKNOWN",
        }],
        "mutation_requested": True,
        "execution": "create_draft",
    },
    "Tue-Sun里随便5天，早晚随便": {
        "edits": [{
            "candidate_days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "work_day_count": 5,
            "day_selection_mode": "FLEXIBLE",
            "shift_mode": "FLEXIBLE",
            "type": "assign",
        }],
        "mutation_requested": True,
        "execution": "create_draft",
    },
    "E10周二到周六都上，班次你看着排": {
        "edits": [{
            "employee_ids": ["E10"],
            "days": ["Tue", "Wed", "Thu", "Fri", "Sat"],
            "shift_mode": "FLEXIBLE",
            "type": "assign",
            "day_selection_mode": "FIXED",
        }],
        "mutation_requested": True,
        "execution": "create_draft",
    },
    "E10这周上5天": {
        "edits": [{
            "employee_ids": ["E10"],
            "type": "assign",
            "work_day_count": 5,
            "work_day_count_mode": "FIXED",
            "day_selection_mode": "UNKNOWN",
            "shift_mode": "UNKNOWN",
        }],
        "mutation_requested": True,
        "execution": "create_draft",
    },
    "Tue-Sun都安排，早晚随便": {
        "edits": [{
            "days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "day_selection_mode": "FIXED",
            "shift_mode": "FLEXIBLE",
            "type": "assign",
        }],
        "mutation_requested": True,
        "execution": "create_draft",
    },
    "从这6天里任选5天": {
        "edits": [{
            "candidate_days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "work_day_count": 5,
            "day_selection_mode": "FLEXIBLE",
            "type": "assign",
        }],
        "mutation_requested": True,
        "execution": "create_draft",
    },
}


@pytest.fixture
def agent_client(dialogue_api_client, semantic_reply):
    from copy import deepcopy

    def fixture(user):
        msg = user["message"]
        if msg in FLEXIBLE_PLANS:
            return deepcopy(FLEXIBLE_PLANS[msg])
        raise ValueError(f"Unknown mock message: {msg}")

    semantic_reply(fixture)
    return dialogue_api_client


def _state(client, conversation, week=WEEK_40):
    response = client.get(
        f"/api/agent/conversations/{conversation}/scenario",
        params={"browser_workspace_id": WORKSPACE, "week_start": week},
    )
    assert response.status_code == 200, response.text
    return response.json()["dialogue_state"]


def _turn(client, conversation, content, turn_id, *, week=WEEK_40):
    response = _send(
        client,
        conversation,
        content,
        client_message_id=turn_id,
        current_week_start=week,
    )
    assert response.status_code == 200, f"{turn_id}: {content}\n{response.text}"
    return response.json(), _state(client, conversation, week)


def test_case_1_flexible_days_and_flexible_shifts_direct_draft(agent_client):
    """Case 1: E10这周安排5天 -> Tue-Sun里随便5天，早晚随便 => Direct Draft."""
    conversation = _conversation(agent_client)

    # Turn 1: E10这周安排5天
    res1, state1 = _turn(agent_client, conversation, "E10这周安排5天", "t1")
    assert len(state1["pending"]) == 1
    pending = state1["pending"][0]
    assert pending["employee_id"] == "E10"
    assert pending["work_day_count"] == 5
    assert res1["schedule_result"] is None

    # Turn 2: Tue-Sun里随便5天，早晚随便
    res2, state2 = _turn(agent_client, conversation, "Tue-Sun里随便5天，早晚随便", "t2")
    # Should resolve all missing info and generate draft directly
    assert len(state2["pending"]) == 0
    assert len(state2["conditions"]) == 1
    condition = state2["conditions"][0]
    assert all(c["employee_id"] == "E10" for c in condition["changes"])
    assert all(c["shift"] is None for c in condition["changes"])
    assert all(c["work_day_count"] == 5 for c in condition["changes"])
    assert set(condition["changes"][0]["candidate_days"]) == {"Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}

    # Must produce a valid draft
    assert res2["schedule_result"] is not None
    assert res2["schedule_result"]["status"] == "feasible"
    assignments = res2["schedule_result"]["schedule"]["assignments"]
    e10_assignments = [a for a in assignments if a["employee_id"] == "E10"]
    # E10 should have exactly 5 shifts, all on Tue-Sun
    assert len(e10_assignments) == 5
    e10_days = {a["day"] for a in e10_assignments}
    assert e10_days.issubset({"Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})
    assert "Mon" not in e10_days


def test_case_2_fixed_days_flexible_shifts_direct_draft(agent_client):
    """Case 2: E10周二到周六都上，班次你看着排 => Direct Draft."""
    conversation = _conversation(agent_client)

    res, state = _turn(agent_client, conversation, "E10周二到周六都上，班次你看着排", "t1")
    assert len(state["pending"]) == 0
    assert len(state["conditions"]) == 1
    condition = state["conditions"][0]
    assert len(condition["changes"]) == 5
    assert all(c["employee_id"] == "E10" for c in condition["changes"])
    assert all(c["shift"] is None for c in condition["changes"])
    assert {c["day"] for c in condition["changes"]} == {"Tue", "Wed", "Thu", "Fri", "Sat"}

    # Must produce a valid draft
    assert res["schedule_result"] is not None
    assert res["schedule_result"]["status"] == "feasible"
    assignments = res["schedule_result"]["schedule"]["assignments"]
    e10_assignments = [a for a in assignments if a["employee_id"] == "E10"]
    assert len(e10_assignments) == 5
    assert {a["day"] for a in e10_assignments} == {"Tue", "Wed", "Thu", "Fri", "Sat"}


def test_case_3_deterministic_conflict_retains_state_and_asks_only_conflict(agent_client):
    """Case 3: E10这周上5天 -> Tue-Sun都安排，早晚随便 => Only ask 5-day vs 6-day conflict."""
    conversation = _conversation(agent_client)

    # Turn 1: E10这周上5天
    res1, state1 = _turn(agent_client, conversation, "E10这周上5天", "t1")
    assert len(state1["pending"]) == 1
    assert state1["pending"][0]["employee_id"] == "E10"
    assert state1["pending"][0]["work_day_count"] == 5

    # Turn 2: Tue-Sun都安排，早晚随便
    res2, state2 = _turn(agent_client, conversation, "Tue-Sun都安排，早晚随便", "t2")
    # Must NOT generate draft due to conflict
    assert res2["schedule_result"] is None
    # Must retain E10 in pending
    assert len(state2["pending"]) == 1
    pending = state2["pending"][0]
    assert pending["employee_id"] == "E10"
    assert pending["shift_mode"] == "FLEXIBLE"
    assert pending["work_day_count"] == 5

    # Must record day_count_conflict
    assert len(state2["conflicts"]) == 1
    conflict = state2["conflicts"][0]
    assert conflict["code"] == "day_count_conflict"
    assert conflict["employee_id"] == "E10"
    assert "6 天都安排" in conflict["message"] or "6天都安排" in conflict["message"]
    assert "任选 5 天" in conflict["message"] or "任选5天" in conflict["message"]

    # The assistant response should ask ONLY the conflict question, not re-ask employee or shift
    reply = res2["assistant_message"]["content"]
    assert "任选" in reply
    assert "6" in reply and "5" in reply
    assert "班次" not in reply or "早晚" not in reply  # never ask for shift

    # Turn 3: User clarifies "从这6天里任选5天"
    res3, state3 = _turn(agent_client, conversation, "从这6天里任选5天", "t3")
    # Conflict is resolved! Direct draft generated!
    assert len(state3["conflicts"]) == 0
    assert len(state3["pending"]) == 0
    assert len(state3["conditions"]) == 1
    assert res3["schedule_result"] is not None
    assert res3["schedule_result"]["status"] == "feasible"
    assignments = res3["schedule_result"]["schedule"]["assignments"]
    e10_assignments = [a for a in assignments if a["employee_id"] == "E10"]
    assert len(e10_assignments) == 5
    assert {a["day"] for a in e10_assignments}.issubset({"Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})
