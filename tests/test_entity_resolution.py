from __future__ import annotations

import pytest

from backend.app.models import Day, RequestIntent, Skill
from backend.app.services.entity_resolver import EntityResolver
from backend.app.services.intent_parser import IntentParser


def _employees(employee_factory):
    return [
        employee_factory("E01", role="manager", skills=[Skill.MANAGER]),
        employee_factory("E13", role="part_time"),
        employee_factory("E14", role="part_time", available_days=[Day.MON]),
        employee_factory("E16", role="part_time"),
    ]


def test_unique_candidate_auto_resolves(employee_factory):
    employees = _employees(employee_factory)

    result = EntityResolver().resolve("E01 周五请假", employees, day=Day.FRI)

    assert result.status == "resolved"
    assert result.employee.id == "E01"


def test_multiple_candidates_require_clarification(employee_factory):
    employees = _employees(employee_factory)

    result = EntityResolver().resolve("那个兼职周五请假", employees, day=Day.FRI)
    payload = result.as_dict()

    assert result.status == "clarification_required"
    assert {item["employee_id"] for item in payload["candidates"]} == {"E13", "E16"}
    assert all("skills" not in item for item in payload["candidates"])


def test_no_candidate_returns_not_found(employee_factory):
    result = EntityResolver().resolve("E999 周五请假", _employees(employee_factory), day=Day.FRI)

    assert result.status == "entity_not_found"
    assert result.candidates == []


def test_fake_llm_employee_id_is_rejected(employee_factory):
    employees = _employees(employee_factory)

    with pytest.raises(LookupError):
        EntityResolver.validate_selected("E999", employees)


def test_role_filter_uses_verified_manager_skill(employee_factory):
    employees = [
        employee_factory("E01", role="manager", skills=[]),
        employee_factory("E02", role="associate", skills=[Skill.MANAGER]),
    ]

    result = EntityResolver().resolve("找经理", employees)

    assert result.status == "resolved"
    assert result.employee.id == "E02"


def test_intent_parser_rejects_unknown_explicit_id(employee_factory):
    parsed = IntentParser().parse(
        "E999 周五请假并重排",
        _employees(employee_factory),
        default_intent=RequestIntent.REPLAN,
    )

    assert parsed.changes == []
    assert parsed.resolution == {"status": "entity_not_found", "unknown_ids": ["E999"]}


def test_intent_parser_returns_structured_clarification(employee_factory):
    parsed = IntentParser().parse(
        "那个兼职周五请假，其他员工尽量少调整",
        _employees(employee_factory),
        default_intent=RequestIntent.REPLAN,
    )

    assert parsed.resolution["status"] == "clarification_required"
    assert parsed.minimize_changes is True

