"""Language interpretation needs a provider; offline mode must never execute it."""
import pytest
from backend.app.models.dialogue import DialogueState
from backend.app.services.dialogue_parser import parse_command
from backend.app.services.llm_client import AgentLLMClient, AIUnavailableError
from tests.evals.scheduling_language import POSITIVE, NEGATIVE
from tests.test_agent import WEEK_40
from tests.test_dialogue_state import _assert_execution_source


@pytest.mark.parametrize("text", POSITIVE + NEGATIVE)
def test_free_text_requires_semantic_provider(text, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "false")
    with pytest.raises(AIUnavailableError):
        parse_command(text, DialogueState(), [], AgentLLMClient())


def assert_draft(client, conversation, payload, shift="morning"):
    result = _assert_execution_source(payload, conversation, "execute", {("E02", "Mon", "assign", shift)})
    context = client.get("/api/schedules/week-context", params={"week_start": WEEK_40}).json()
    assert context["draft_schedule"]["schedule_id"] == result["schedule_id"]
    assert context["draft_schedule"]["status"] == "draft"
    assert any(t["tool_name"] in {"generate_schedule", "replan_schedule"} for t in payload["tool_calls"])
    return result
