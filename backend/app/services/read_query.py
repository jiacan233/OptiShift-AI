"""Validation and deterministic tool dispatch for LLM-supplied read plans."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models import Day, Employee, Shift, WEEK_DAYS

PROMPT_VERSION = "agent-read-v2"
from ..models.dialogue import ReadQueryPlan, QuestionType, FactName

def normalize_plan(content: str, employees: list[Employee], *, target_week: date | None = None,
                   proposal: ReadQueryPlan | dict | None = None) -> ReadQueryPlan:
    """Validate a typed plan. The message is deliberately never interpreted here."""
    plan = ReadQueryPlan.model_validate(proposal or {})
    unknown = set(plan.employee_ids) - {e.id for e in employees}
    if unknown:
        raise ValueError("Unknown employee IDs: " + ", ".join(sorted(unknown)))
    return plan.model_copy(update={"target_week": target_week or plan.target_week})


# Fixed server-owned dispatch. Models never return callable names.
READ_TOOL_MAP = {
    "schedule_overview": "analyze_staffing", "staffing_explanation": "analyze_staffing",
    "assignment_explanation": "analyze_staffing", "coverage_analysis": "analyze_staffing",
    "employee_workload": "analyze_staffing", "rule_explanation": "analyze_staffing",
    "schedule_difference": "analyze_staffing", "feasibility_explanation": "analyze_staffing",
    "general_question": "analyze_staffing",
}
READ_TOOL_ALLOWLIST = frozenset({"get_current_schedule", "analyze_staffing", "analyze_counterfactual"})


def tool_for_plan(plan: ReadQueryPlan) -> str:
    return "analyze_counterfactual" if plan.whether_counterfactual_needed else READ_TOOL_MAP[plan.question_type]
