"""Typed read plans and text-grounded corrections, independent of write intents."""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models import Day, Employee, Shift, WEEK_DAYS
from .intent_parser import IntentParser, _normalize_identifier_text

PROMPT_VERSION = "agent-read-v2"
QuestionType = Literal[
    "schedule_overview", "staffing_explanation", "assignment_explanation",
    "coverage_analysis", "employee_workload", "rule_explanation",
    "schedule_difference", "feasibility_explanation", "general_question",
]
FactName = Literal["staffing", "coverage", "assignments", "workload", "rules", "validation", "difference", "counterfactual"]


class ReadQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: QuestionType = "general_question"
    target_week: date | None = None
    day: Day | None = None
    shift: Shift | None = None
    employee_ids: list[str] = Field(default_factory=list)
    scope: Literal["per_shift", "per_day"] = "per_day"
    requested_facts: list[FactName] = Field(default_factory=list)
    comparison: Literal["none", "previous_version"] = "none"
    reference_mode: Literal["none", "suggestion"] = "none"
    whether_counterfactual_needed: bool = False
    version: int | None = Field(default=None, ge=1)
    clarification: str | None = None


def explicit_reference(content: str) -> str | None:
    """No model output or conversation history is evidence of a reference."""
    text = _normalize_identifier_text(content).lower()
    if re.search(r"(?:不要|别|不必|不想).{0,8}(?:引用|建议)|(?:只|仅).{0,5}当前排班", text):
        return None
    # Concrete schedule objects take precedence over references.
    if IntentParser.extract_days(text) or re.search(r"(?<![A-Za-z0-9_])e\d+(?![A-Za-z0-9_])|早班|晚班|\b(?:morning|evening)\b|\d+\s*/\s*\d+|\d+\s*个人|\d{4}-\d{2}-\d{2}|\d+月\d+(?:日|号)", text):
        return None
    match = re.search(r"(?:第\s*([一二两三四五六七八九十\d]+)\s*(?:条|个)|suggestion[_ ]?(\d+))", text)
    if match:
        raw = match.group(1) or match.group(2)
        ordinal = int(raw) if raw.isdigit() else {c: i for i, c in enumerate("一二三四五六七八九十", 1)}.get(raw, 2 if raw == "两" else None)
        if ordinal:
            return f"suggestion_{ordinal}"
    if re.search(r"(?:这个|那个|刚才|之前).{0,8}(?:建议|方案)|按这个(?:改|调整)|that suggestion", text):
        return "previous_message"
    return None


def is_counterfactual(content: str) -> bool:
    # Analysis of removing an assignment is distinct from temporary leave scenarios.
    return bool(re.search(
        r"少\s*(?:一|1)\s*(?:个)?人|(?:去掉|移除).*(?:吗|么|行|如果|会)|"
        r"(?:如果|假如).*(?:去掉|移除)|(?:是不是|是否)必须|能不能不排|"
        r"(?:remove|without).*(?:shift|employee)|fewer.*staff", content.lower()
    ))


def is_read_only_question(content: str) -> bool:
    """Feasibility questions do not authorize a draft or scenario mutation."""
    from .turn_semantics import non_scheduling_semantics
    if non_scheduling_semantics(content):
        return True
    if re.search(r"帮我.*(?:试排|排一下)|生成看看|重新排|就这么排|给我出一版|试排一下|请.*生成", content, re.I):
        return False
    return bool(re.search(r"能不能|行不行|能排吗|能排不|是否可以|可不可以|只是问|(?:如果|假如).*(?:会|怎样|如何)|can .* be scheduled", content, re.I))


def classify(content: str, employees: list[str]) -> QuestionType:
    text = content.lower()
    if is_counterfactual(text):
        return "assignment_explanation" if employees else "staffing_explanation"
    if is_read_only_question(text) and re.search(r"排|schedule", text):
        return "feasibility_explanation"
    if re.search(r"版本.*(?:改|差|区别)|version.*(?:diff|chang)", text):
        return "schedule_difference"
    if re.search(r"排不了|不可行|infeasib", text):
        return "feasibility_explanation"
    if re.search(r"最忙|工作量|负荷|workload|多少.*班|几个班", text):
        return "employee_workload"
    if re.search(r"违反|合规|校验|validate|coverage|谁.*(?:饮品|收银|店长)|覆盖", text):
        return "coverage_analysis"
    if employees and re.search(r"为什么|原因|why|必须", text):
        return "assignment_explanation"
    if re.search(r"人数|几个人|\d+\s*个人|\d+\s*/\s*\d+|够|staffing", text):
        return "staffing_explanation"
    if re.search(r"规则|rule", text):
        return "rule_explanation"
    if IntentParser.extract_days(text) or re.search(r"谁.*上班|当前排班|排班.*(?:概览|情况)|schedule overview", text):
        return "schedule_overview"
    return "general_question"


def normalize_plan(content: str, employees: list[Employee], *, target_week: date | None = None,
                   proposal: ReadQueryPlan | dict | None = None) -> ReadQueryPlan:
    text = _normalize_identifier_text(content)
    ids = sorted(set(m.upper() for m in re.findall(r"(?<![A-Za-z0-9_])[eE]\d{1,4}(?![A-Za-z0-9_])", text)))
    known = {e.id for e in employees}
    clarification = None
    if set(ids) - known:
        clarification = "员工主数据中不存在：" + "、".join(sorted(set(ids) - known)) + "，请核对员工编号。"
    try:
        suggested = ReadQueryPlan.model_validate(proposal or {})
    except (ValidationError, TypeError):
        suggested = ReadQueryPlan()
    days = IntentParser.extract_days(text)
    # Calendar dates are resolved with the same backend parser as week selection.
    from .agent_context import WeekResolver, WeekResolutionError
    try:
        explicit_date = WeekResolver._explicit_date(text, target_week) if target_week or re.search(r"\d{4}[-年]", text) else None
    except WeekResolutionError as exc:
        explicit_date = None
        clarification = exc.question
    if explicit_date:
        days = [WEEK_DAYS[explicit_date.weekday()]]
    shifts = [shift for shift, pattern in ((Shift.MORNING, r"早班|\bmorning\b"), (Shift.EVENING, r"晚班|\bevening\b")) if re.search(pattern, text.lower())]
    if len(days) > 1:
        clarification = "请一次指定一天进行分析。"
    question = classify(text, ids)
    if question == "general_question" and not explicit_reference(content):
        question = suggested.question_type
    counterfactual = is_counterfactual(text)
    # A model can ask for analysis, but cannot invent removal authorization or entities.
    facts: list[FactName] = {
        "schedule_overview": ["staffing", "coverage", "assignments"],
        "staffing_explanation": ["staffing", "coverage", "validation"],
        "assignment_explanation": ["assignments", "staffing", "coverage", "workload"],
        "coverage_analysis": ["staffing", "coverage", "assignments", "validation"],
        "employee_workload": ["workload"], "rule_explanation": ["rules"],
        "schedule_difference": ["difference"], "feasibility_explanation": ["validation"],
        "general_question": [],
    }[question]
    if counterfactual:
        facts = [*facts, "counterfactual"]
    version_match = re.search(r"(?:\bv\s*|版本\s*|第\s*)(\d+)\s*(?:版)?", text, re.I)
    # '第 2 条' is a suggestion, not a schedule version.
    version = int(version_match.group(1)) if version_match and re.search(r"\bv\s*\d|版本\s*\d|第\s*\d+\s*版", text, re.I) else None
    return ReadQueryPlan(
        question_type=question, target_week=target_week, day=days[0] if len(days) == 1 else None,
        shift=shifts[0] if len(shifts) == 1 else None, employee_ids=ids,
        scope="per_shift" if len(shifts) == 1 else "per_day", requested_facts=facts,
        comparison="previous_version" if question == "schedule_difference" else "none",
        reference_mode="suggestion" if explicit_reference(content) else "none",
        whether_counterfactual_needed=counterfactual, version=version, clarification=clarification,
    )


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
