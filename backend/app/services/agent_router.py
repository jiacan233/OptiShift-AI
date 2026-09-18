from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models import ChangeType, Day, Employee, ScheduleChange
from .intent_parser import DAY_TOKENS
from .llm_client import AIUnavailableError, AgentLLMClient


class UnknownAgentEmployeeError(ValueError):
    def __init__(self, employee_ids: list[str]) -> None:
        self.employee_ids = employee_ids
        super().__init__(f"Unknown employee IDs: {', '.join(employee_ids)}")


class AgentIntent(StrEnum):
    GENERATE = "generate"
    REPLAN = "replan"
    VALIDATE = "validate"
    ADVICE = "advice"
    EXPLAIN = "explain"
    ASK = "ask"
    CLARIFICATION = "clarification"
    OUT_OF_SCOPE = "out_of_scope"


class AgentReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "previous_message", "suggestion"] = "none"
    suggestion_id: str | None = None


class AgentClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    question: str | None = None


class AgentRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: AgentIntent
    mutation_requested: bool = False
    target_week: date | None = None
    target_iso_year: int | None = Field(default=None, ge=0, le=9999)
    # The WeekResolver owns semantic ISO-week validation so invalid user input can
    # produce a clarification instead of failing route construction.
    target_iso_week: int | None = Field(default=None, ge=0, le=99)
    employees: list[str] = Field(default_factory=list)
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = False
    reference: AgentReference = Field(default_factory=AgentReference)
    clarification: AgentClarification = Field(default_factory=AgentClarification)


class TrustedAgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["generate", "replan", "validate", "advice"]
    target_week: date | None = None
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = True


class AgentRouter:
    def __init__(self, llm: AgentLLMClient | None = None) -> None:
        self.llm = llm or AgentLLMClient()

    def route(
        self,
        content: str,
        *,
        employees: list[Employee],
        recent_messages: list[dict[str, Any]],
        conversation_summary: str | None = None,
        trusted_action: TrustedAgentAction | None = None,
    ) -> AgentRoute:
        if self._confirmation_only(content):
            return AgentRoute(intent=AgentIntent.ASK, mutation_requested=False)
        if trusted_action is not None:
            known = {employee.id for employee in employees}
            referenced = {item.employee_id for item in trusted_action.changes}
            unknown = sorted(referenced - known)
            if unknown:
                raise UnknownAgentEmployeeError(unknown)
            intent = AgentIntent(trusted_action.intent)
            return AgentRoute(
                intent=intent,
                mutation_requested=intent in {AgentIntent.GENERATE, AgentIntent.REPLAN},
                target_week=trusted_action.target_week,
                changes=trusted_action.changes,
                employees=sorted({item.employee_id for item in trusted_action.changes}),
                minimize_changes=trusted_action.minimize_changes,
            )
        if not self.llm.enabled:
            return self._deterministic_route(content, employees)

        nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        nullable_integer = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "intent": {"type": "string", "enum": [item.value for item in AgentIntent]},
                "mutation_requested": {"type": "boolean"},
                "target_week": nullable_string,
                "target_iso_year": nullable_integer,
                "target_iso_week": nullable_integer,
                "employees": {"type": "array", "items": {"type": "string"}},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "employee_id": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [item.value for item in ChangeType],
                            },
                            "day": {"type": "string", "enum": [item.value for item in Day]},
                            "shift": {
                                "anyOf": [
                                    {"type": "string", "enum": ["morning", "evening"]},
                                    {"type": "null"},
                                ]
                            },
                        },
                        "required": ["employee_id", "type", "day", "shift"],
                    },
                },
                "minimize_changes": {"type": "boolean"},
                "reference": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["none", "previous_message", "suggestion"],
                        },
                        "suggestion_id": nullable_string,
                    },
                    "required": ["type", "suggestion_id"],
                },
                "clarification": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "required": {"type": "boolean"},
                        "question": nullable_string,
                    },
                    "required": ["required", "question"],
                },
            },
            "required": [
                "intent",
                "mutation_requested",
                "target_week",
                "target_iso_year",
                "target_iso_week",
                "employees",
                "changes",
                "minimize_changes",
                "reference",
                "clarification",
            ],
        }
        payload = self.llm.complete_json(
            system=(
                "Route a scheduling assistant message into the supplied JSON schema. "
                "Separate analysis from mutation: advice about leave is read only unless the "
                "user explicitly asks to generate or replan. Never treat confirmation words as "
                "permission to confirm a schedule; confirmation remains a UI-only action. Use "
                "only supplied employee IDs. Resolve references such as 'second one' to a "
                "suggestion reference when supported by recent messages."
            ),
            user={
                "message": content,
                "conversation_summary": conversation_summary,
                "valid_employee_ids": [employee.id for employee in employees],
                "recent_messages": recent_messages[-12:],
            },
            schema_name="agent_route",
            schema=schema,
        )
        try:
            route = AgentRoute.model_validate(payload)
        except ValidationError as exc:
            raise AIUnavailableError(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
            ) from exc

        known = {employee.id for employee in employees}
        referenced = set(route.employees) | {item.employee_id for item in route.changes}
        unknown = sorted(referenced - known)
        if unknown:
            raise UnknownAgentEmployeeError(unknown)
        return route

    @staticmethod
    def _confirmation_only(content: str) -> bool:
        return content.strip().lower().strip("。.!！ ") in {
            "确认",
            "应用",
            "就这样",
            "可以",
            "确认这个版本",
        }

    @staticmethod
    def _extract_day(content: str) -> Day | None:
        normalized = content.lower()
        for day, tokens in DAY_TOKENS.items():
            if any(token in normalized for token in tokens):
                return day
        return None

    @classmethod
    def _deterministic_route(
        cls, content: str, employees: list[Employee]
    ) -> AgentRoute:
        text = content.strip()
        normalized = text.lower()
        known = {employee.id for employee in employees}
        referenced_ids = {
            match.upper() for match in re.findall(r"\b[eE]\d{1,4}\b", text)
        }
        unknown = sorted(referenced_ids - known)
        if unknown:
            raise UnknownAgentEmployeeError(unknown)
        employee_ids = sorted(referenced_ids)

        reference = AgentReference()
        ordinal = re.search(r"(?:第\s*([一二两三四五六七八九十\d]+)\s*条|suggestion[_ ]?(\d+))", normalized)
        if ordinal:
            raw = ordinal.group(1) or ordinal.group(2) or ""
            chinese = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
            number = int(raw) if raw.isdigit() else chinese.get(raw)
            if number:
                reference = AgentReference(type="suggestion", suggestion_id=f"suggestion_{number}")
        elif any(token in normalized for token in ("按这个", "这个建议", "that one", "this one")):
            reference = AgentReference(type="previous_message")

        confirmation_only = cls._confirmation_only(content)
        mutation_terms = (
            "重新排",
            "重排",
            "帮我排",
            "排一版",
            "生成",
            "按这个改",
            "按第二条改",
            "replan",
            "generate",
        )
        mutation_requested = any(term in normalized for term in mutation_terms)
        reference_apply = reference.type != "none" and any(
            term in normalized for term in ("调整", "改", "应用", "apply")
        )
        mutation_requested = mutation_requested or reference_apply

        out_of_scope_terms = (
            "天气",
            "股票",
            "比特币",
            "菜谱",
            "写代码",
            "weather",
            "stock price",
            "recipe",
        )
        if any(term in normalized for term in out_of_scope_terms):
            intent = AgentIntent.OUT_OF_SCOPE
            mutation_requested = False
        elif confirmation_only:
            intent = AgentIntent.ASK
            mutation_requested = False
        elif reference_apply or any(
            term in normalized
            for term in ("重新排", "重排", "调整排班", "按这个改", "replan")
        ):
            intent = AgentIntent.REPLAN
        elif any(term in normalized for term in ("生成", "排一版", "新排班", "generate")):
            intent = AgentIntent.GENERATE
        elif any(term in normalized for term in ("校验", "检查排班", "违反规则", "validate")):
            intent = AgentIntent.VALIDATE
        elif any(term in normalized for term in ("为什么", "原因", "explain")):
            intent = AgentIntent.EXPLAIN
        elif any(term in normalized for term in ("建议", "优化", "影响", "advice")):
            intent = AgentIntent.ADVICE
        else:
            intent = AgentIntent.ASK

        day = cls._extract_day(text)
        leave = any(term in normalized for term in ("请假", "不可工作", "别排", "leave", "unavailable"))
        changes = (
            [
                ScheduleChange(employee_id=employee_id, type=ChangeType.LEAVE, day=day)
                for employee_id in employee_ids
            ]
            if day is not None and leave
            else []
        )

        target_week = None
        date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if date_match:
            try:
                target_week = date.fromisoformat(date_match.group(1))
            except ValueError:
                target_week = None
        iso_match = re.search(r"(?:(\d{4})\s*年\s*)?第\s*(\d{1,2})\s*周", text)
        if iso_match is None:
            iso_match = re.search(
                r"(?:(\d{4})\s*[-/]?\s*)?\b(?:week|wk)\s*(\d{1,2})\b",
                text,
                re.IGNORECASE,
            )

        clarification = AgentClarification()
        if leave and not employee_ids:
            clarification = AgentClarification(
                required=True, question="请说明需要调整的员工编号。"
            )
            intent = AgentIntent.CLARIFICATION
            mutation_requested = False
        elif leave and day is None:
            clarification = AgentClarification(
                required=True, question="请说明请假或不可工作的具体日期。"
            )
            intent = AgentIntent.CLARIFICATION
            mutation_requested = False

        return AgentRoute(
            intent=intent,
            mutation_requested=mutation_requested,
            target_week=target_week,
            target_iso_year=int(iso_match.group(1)) if iso_match and iso_match.group(1) else None,
            target_iso_week=int(iso_match.group(2)) if iso_match else None,
            employees=employee_ids,
            changes=changes,
            minimize_changes=any(
                term in normalized for term in ("尽量少", "最小调整", "不要动", "minimize")
            ),
            reference=reference,
            clarification=clarification,
        )
