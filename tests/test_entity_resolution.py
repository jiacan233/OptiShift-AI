"""Entity identities are validated; free-form entity meaning requires the LLM."""
import pytest
from backend.app.models import RequestIntent
from backend.app.models.dialogue import TurnCommand
from backend.app.services.entity_resolver import EntityResolver
from backend.app.services.intent_parser import IntentParser
from backend.app.services.llm_client import AIUnavailableError
from tests.test_agent_router import LLM, EMP, plan, edit

@pytest.mark.parametrize("employee", ["E01", "E07", "E20"])
def test_selected_identity_exists(employee):
    assert EntityResolver.validate_selected(employee, EMP).id == employee

@pytest.mark.parametrize("employee", ["E99", "unknown", ""])
def test_unknown_selection_rejected(employee):
    with pytest.raises(LookupError):
        EntityResolver.validate_selected(employee, EMP)

@pytest.mark.parametrize("text", ["E01 周五请假", "那个兼职周五请假", "找经理"])
def test_entity_meaning_has_no_offline_fallback(text, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "false")
    with pytest.raises(AIUnavailableError):
        EntityResolver().resolve(text, EMP)

def test_prompt_adapter_preserves_typed_conditions():
    parsed = IntentParser(llm=LLM(plan(execution="create_draft"))).parse("opaque", EMP)
    assert parsed.changes[0].employee_id == "E07"
    assert parsed.changes[0].type == "unavailable"

@pytest.mark.parametrize("command", [plan(suppress_execution=True), TurnCommand(clarification="未知员工"), TurnCommand(edits=[edit()],execution="analyze",declared_condition_count=1)])
def test_direct_generation_cannot_bypass_clarification_or_suppression(command):
    parsed = IntentParser(llm=LLM(command)).parse("opaque", EMP, default_intent=RequestIntent.REPLAN)
    assert parsed.resolution["status"] == "clarification_required"
    assert parsed.changes == []
