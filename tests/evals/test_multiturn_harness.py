"""Acceptance-oracle regressions: old cards and HTTP 200 cannot produce a pass."""

import json
from copy import deepcopy
from pathlib import Path

from scripts.agent_multiturn_live import case_checks, dialogue_state, digest, snapshot


def minimal_case():
    condition = {"employee_id": "E18", "day": "Thu", "type": "assign", "shift": "evening"}
    case = {
        "week_start": "2026-10-05",
        "turns": [{"kind": "message", "content": "按这个条件重新排班。"}],
        "expected_conditions": [condition],
        "requires_new_draft": True,
        "allow_infeasible": False,
    }
    final = {
        "conversation_scenarios": [
            {
                "conversation_id": "conversation",
                "week_start": case["week_start"],
                "temporary_constraints": [condition],
            }
        ],
        "conversation_dialogue_states": [
            {
                "conversation_id": "conversation",
                "week_start": case["week_start"],
                "payload": {"scenario_revision": 1, "conditions": [{"changes": [condition]}]},
            }
        ],
    }
    turn = {
        "original_turn": "1",
        "inserted": False,
        "request": {"content": case["turns"][0]["content"], "client_message_id": "client"},
        "terminal": {"event": "result"},
        "settled": True,
        "persisted_assistant_messages": [{"content": "已生成草稿。"}],
        "state_after": final,
        "new_schedules": [
            {
                "schedule_id": "new",
                "status": "draft",
                "validation_json": {"passed": True},
                "metadata_json": {
                    "requested_changes": [condition],
                    "agent_conversation_id": "conversation",
                    "agent_client_message_id": "client",
                    "scenario_revision": 1,
                    "condition_snapshot": [condition],
                    "condition_hash": digest([condition]),
                    "dependency_hash": "dependencies",
                },
            }
        ],
    }
    return case, [turn], final


def failures(case, turns, final):
    return {c["check"] for c in case_checks(case, turns, final, "conversation") if not c["passed"]}


def test_complete_chain_is_required():
    case, turns, final = minimal_case()
    assert failures(case, turns, final) == set()
    turns[0]["new_schedules"] = []
    final["schedules"] = [{"schedule_id": "old", "status": "draft"}]
    assert "final_turn_creates_new_draft" in failures(case, turns, final)


def test_http_200_without_terminal_is_failure():
    case, turns, final = minimal_case()
    turns[0].update(http_status=200, terminal=None)
    assert "T1:terminal_sse_received" in failures(case, turns, final)


def test_sse_business_error_is_not_http_success():
    case, turns, final = minimal_case()
    turns[0]["terminal"] = {"event": "error", "data": {"code": "draft_pending"}}
    assert "T1:business_result_received" in failures(case, turns, final)


def test_empty_solver_changes_cannot_pass_recorded_conditions():
    case, turns, final = minimal_case()
    turns[0]["new_schedules"][0]["metadata_json"]["requested_changes"] = []
    assert "draft_solver_conditions_match_specification" in failures(case, turns, final)


def test_old_source_client_cannot_count_as_this_turn():
    case, turns, final = minimal_case()
    turns[0]["new_schedules"][0]["metadata_json"]["agent_client_message_id"] = "old-client"
    assert "draft_source_client_message" in failures(case, turns, final)


def test_condition_hash_must_cover_the_recorded_snapshot():
    case, turns, final = minimal_case()
    turns[0]["new_schedules"][0]["metadata_json"]["condition_hash"] = "stale"
    assert "draft_condition_hash_matches_snapshot" in failures(case, turns, final)


def test_variant_corpus_is_opt_in_and_inherits_original_oracle():
    from scripts.agent_multiturn_live import load_cases

    selected = {"CASE_A", "CASE_B", "CASE_E", "CASE_G", "CASE_H", "CASE_J"}
    _, original = load_cases(selected=selected, include_variants=False)
    _, variants = load_cases(selected=selected, include_variants=True)
    assert {case["id"] for case in original} == selected
    assert {case["id"] for case in variants} == selected | {
        f"{case}_VARIANT_1" for case in selected
    }
    base = next(case for case in variants if case["id"] == "CASE_A")
    variant = next(case for case in variants if case["id"] == "CASE_A_VARIANT_1")
    assert variant["expected_conditions"] == base["expected_conditions"]


def test_variant_refresh_turn_remains_non_message_action():
    from scripts.agent_multiturn_live import load_cases

    _, cases = load_cases(selected={"CASE_J"}, include_variants=True)
    variant = next(case for case in cases if case["id"] == "CASE_J_VARIANT_1")
    assert variant["turns"][4]["kind"] == "browser_refresh"
    assert variant["turns"][4]["content"] == next(
        turn["content"] for turn in cases[0]["turns"] if turn["kind"] == "browser_refresh"
    )


def test_dialogue_state_is_scoped_to_conversation_and_week():
    _, _, final = minimal_case()
    assert dialogue_state(final, "other", "2026-10-05") == {}
    assert dialogue_state(final, "conversation", "2026-10-12") == {}
    assert dialogue_state(final, "conversation", "2026-10-05")["scenario_revision"] == 1


def test_snapshot_is_complete_and_read_only(tmp_path):
    import sqlite3

    database = tmp_path / "snapshot.db"
    payload = {"long_text": "x" * 50_000}
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE evidence (id TEXT, payload TEXT)")
        connection.execute("INSERT INTO evidence VALUES (?, ?)", ("one", json.dumps(payload)))
    before = database.read_bytes()
    assert snapshot(database)["evidence"] == [{"id": "one", "payload": payload}]
    assert database.read_bytes() == before


def test_original_corpus_contains_all_messages_and_j_refresh_is_not_text():
    path = Path(__file__).with_name("multiturn_cases.json")
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert [case["id"] for case in cases] == [f"CASE_{letter}" for letter in "ABCDEFGHIJKLMN"]
    assert sum(t["kind"] == "message" for c in cases for t in c["turns"]) == 112
    refresh = next(c for c in cases if c["id"] == "CASE_J")["turns"][4]
    assert refresh["kind"] == "browser_refresh"
    assert "不是发送文字" in refresh["content"]


def test_intermediate_pending_must_retain_slots():
    case, turns, final = minimal_case()
    case = deepcopy(case)
    case["checkpoints"] = {"1": {"pending_contains": {"employee_id": "E18", "days": ["Thu"]}}}
    assert "T1:pending_contains" in failures(case, turns, final)
