"""Opt-in real Provider + persisted Agent/Solver evaluation; no mocked routing.

LIVE_SCHEDULING_EVAL=true; LLM_EVAL_OUTPUT_DIR must point outside the repository.
The provider's raw interpretation is diagnostic, never the expectation oracle.
"""
import json
import os
from pathlib import Path

import pytest

from backend.app.services.agent_router import AgentRouter
from tests.evals.scheduling_language import MULTITURN, NEGATIVE, POSITIVE
from tests.evals.test_live_agent_eval import RecordingLLM
from tests.test_agent import _conversation
from tests.test_dialogue_state import _assert_no_draft, _turn, agent_client
from tests.test_scheduling_language import assert_draft

CASES = (
    [(f"positive-{i+1}", [text], "morning") for i, text in enumerate(POSITIVE)]
    + [(f"negative-{i+1}", [text], None) for i, text in enumerate(NEGATIVE)]
    + [(f"multi-{i+1}", turns, shift) for i, (turns, shift) in enumerate(MULTITURN)]
    + [("suppress-pending", ["帮我把E02排进去", "周一，不过先别生成", "早班"], None),
       ("hypothetical-pending", ["如果让E02这周上班会怎样", "周一", "早班"], None)]
)


@pytest.mark.skipif(os.getenv("LIVE_SCHEDULING_EVAL") != "true", reason="real Provider evaluation is opt-in")
@pytest.mark.parametrize("name,turns,shift", CASES, ids=[c[0] for c in CASES])
def test_live_scheduling_language(agent_client, monkeypatch, name, turns, shift):
    from backend.app.api import dependencies as deps

    root = Path(os.environ["LLM_EVAL_OUTPUT_DIR"]).resolve()
    assert not root.is_relative_to(Path(__file__).resolve().parents[2])
    root.mkdir(parents=True, exist_ok=True)
    llm = RecordingLLM()
    assert llm.api_key, "LLM_API_KEY is required"
    router = AgentRouter(llm)
    monkeypatch.setattr(deps.agent_service, "llm", llm)
    monkeypatch.setattr(deps.agent_service, "router", router)
    monkeypatch.setattr(deps.scheduling_service.explanations, "llm", llm)
    monkeypatch.setattr(deps.scheduling_service.intent_parser, "llm", llm)
    record = {"name": name, "turns": turns, "expected_shift": shift, "model": llm.model, "status": "failed"}
    try:
        # Independently exercise the existing real Provider router, including
        # language now handled without asking the model for execution authority.
        raw = router.route(turns[0], employees=deps.employee_repository.list(), recent_messages=[])
        record["provider_route"] = raw.model_dump(mode="json")
        assert any(o.get("provider_status") == 200 for o in llm.outputs), "No actual provider HTTP 200"
        conversation = _conversation(agent_client)
        results = []
        for i, text in enumerate(turns):
            final = i == len(turns) - 1
            payload, state = _turn(agent_client, conversation, text, "execute" if final else str(i))
            results.append(payload)
            if not final or shift is None:
                assert not (payload.get("schedule_result") or {}).get("schedule_id")
                _assert_no_draft(agent_client)
        if shift:
            assert_draft(agent_client, conversation, payload, shift)
        record["results"] = results
        record["status"] = "passed"
    finally:
        record["provider_calls"] = llm.outputs
        (root / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
