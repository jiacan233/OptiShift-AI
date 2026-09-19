from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..execution import traced
from ..models import Assignment, ChangeType, Day, Employee, OverrideScope, ScheduleChange, Shift
from .intent_parser import DAY_TOKENS, IntentParser, _normalize_identifier_text
from .llm_client import (
    AgentLLMClient,
    AIUnavailableError,
    strict_json_schema,
)


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
    WHAT_IF = "what_if"


class AgentReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "previous_message", "suggestion"] = "none"
    suggestion_id: str | None = None


class AgentClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    question: str | None = None


class AgentScenarioOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add", "set", "remove", "clear"] = "add"
    employee_id: str
    type: ChangeType = ChangeType.LEAVE
    day: Day | None = None
    shift: Shift | None = None


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
    # Ordered operations are authoritative for scenario mutations.  ``changes``
    # and the legacy global operation remain for older clients.
    operations: list[AgentScenarioOperation] = Field(default_factory=list)
    # Structured scenario operation. Execution must use this value instead of
    # rescanning the user's prose after routing has completed.
    operation: Literal["add", "set", "remove", "clear"] = "add"
    minimize_changes: bool = False
    # The model may identify an explicit authorization request, but the
    # deterministic service validates the exact scope before any write.
    override_requested: bool = False
    force_generate: bool = False
    requested_overrides: list[OverrideScope] = Field(default_factory=list)
    forced_assignments: list[Assignment] = Field(default_factory=list)
    authorization_reason: str | None = Field(default=None, max_length=2000)
    reference: AgentReference = Field(default_factory=AgentReference)
    clarification: AgentClarification = Field(default_factory=AgentClarification)


def agent_route_json_schema() -> dict[str, Any]:
    """Derive the provider contract from the same models used to parse its reply."""
    return strict_json_schema(AgentRoute.model_json_schema())


class TrustedAgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["generate", "replan", "validate", "advice"]
    target_week: date | None = None
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = True
    override_requested: bool = False
    force_generate: bool = False
    requested_overrides: list[OverrideScope] = Field(default_factory=list)
    forced_assignments: list[Assignment] = Field(default_factory=list)
    authorization_reason: str | None = Field(default=None, max_length=2000)


class AgentRouter:
    def __init__(self, llm: AgentLLMClient | None = None) -> None:
        self.llm = llm or AgentLLMClient()

    @traced("agent_route")
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
            return self._validate_force_route(AgentRoute(
                intent=intent,
                mutation_requested=intent in {AgentIntent.GENERATE, AgentIntent.REPLAN},
                target_week=trusted_action.target_week,
                changes=trusted_action.changes,
                employees=sorted({item.employee_id for item in trusted_action.changes}),
                minimize_changes=trusted_action.minimize_changes,
                override_requested=trusted_action.override_requested,
                force_generate=trusted_action.force_generate,
                requested_overrides=trusted_action.requested_overrides,
                forced_assignments=trusted_action.forced_assignments,
                authorization_reason=trusted_action.authorization_reason or content,
            ))
        if not self.llm.enabled:
            return self._deterministic_route(content, employees)

        schema = agent_route_json_schema()
        payload = self.llm.complete_json(
            system=(
                "Route a scheduling assistant message into the supplied JSON schema. "
                "Separate analysis from mutation: advice about leave is read only unless the "
                "user explicitly asks to generate or replan. Never treat confirmation words as "
                "permission to confirm a schedule; confirmation remains a UI-only action. Use "
                "only supplied employee IDs. Resolve references such as 'second one' to a "
                "suggestion reference when supported by recent messages. Set operation to "
                "add, set, remove, or clear from the structured plan; preserve one change "
                "per employee/day and do not invent a cross-product. Populate operations with "
                "ordered per-employee add/set/remove/clear operations; a clear operation may "
                "have day null. Use null for unspecified nullable fields. For changes of type "
                "preference, assign, or unassign, shift must be specified. Treat only direct "
                "statements such as 'force generate' or 'I authorize this exception' as an "
                "override request. An override needs exact rule/day/shift scope: R08 also needs "
                "an employee, while R01-R04 need allowed_shortage. Do not infer an override "
                "from 'try', 'continue', or other ambiguous wording."
            ),
            user={
                "message": content,
                "conversation_summary": conversation_summary,
                "valid_employee_ids": [employee.id for employee in employees],
                "recent_messages": recent_messages[-12:],
            },
            stage="agent_route",
            schema_name="agent_route",
            schema=schema,
        )
        try:
            route = AgentRoute.model_validate(payload)
        except ValidationError as exc:
            raise AIUnavailableError(
                "AI Provider 返回了无法识别的响应。",
                error_type="structured_output_error",
                stage="agent_route",
                latency_ms=self.llm._last_latency_ms,
            ) from exc

        known = {employee.id for employee in employees}
        referenced = set(route.employees) | {item.employee_id for item in route.changes}
        referenced |= {item.employee_id for item in route.operations}
        referenced |= {item.employee_id for item in route.forced_assignments}
        referenced |= {item.employee_id for item in route.requested_overrides if item.employee_id}
        unknown = sorted(referenced - known)
        if unknown:
            raise UnknownAgentEmployeeError(unknown)
        if not route.operations and route.changes:
            route.operations = [
                AgentScenarioOperation(
                    operation=route.operation,
                    employee_id=change.employee_id,
                    type=change.type,
                    day=change.day,
                    shift=change.shift,
                )
                for change in route.changes
            ]
        if (route.force_generate or route.requested_overrides or route.forced_assignments) and not self._explicit_authorization(content):
            return AgentRoute(intent=AgentIntent.CLARIFICATION, clarification=AgentClarification(
                required=True, question="若要突破规则，请明确说明授权例外及其员工、日期、班次或允许缺口。"
            ))
        route.authorization_reason = content if route.force_generate else None
        return self._validate_force_route(route)

    @staticmethod
    def _explicit_authorization(content: str) -> bool:
        return any(term in content.lower() for term in (
            "强制", "我授权", "允许", "即使", "还是让", "就是让", "仍然安排", "仍要安排",
            "没有店长也先", "规则先不", "限制先不", "force", "authorize", "override",
        )) and not any(term in content.lower() for term in (
            "不要强制", "别强制", "不能强制", "不授权", "不允许", "不强制",
            "do not override", "don't override", "do not force", "don't force",
        ))

    @staticmethod
    def _validate_force_route(route: AgentRoute) -> AgentRoute:
        if not (route.force_generate or route.override_requested or route.requested_overrides or route.forced_assignments):
            return route
        if not route.force_generate or not route.authorization_reason:
            return route.model_copy(update={
                "intent": AgentIntent.CLARIFICATION,
                "mutation_requested": False,
                "force_generate": False,
                "clarification": AgentClarification(
                    required=True,
                    question="请明确要授权的规则、具体日期和班次；请假或不可用例外还需要员工编号。",
                ),
            })
        return route.model_copy(update={
            "intent": AgentIntent.GENERATE,
            "mutation_requested": True,
            "override_requested": bool(route.requested_overrides),
            "changes": [],
            "operations": [],
        })

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
        return IntentParser.extract_day(content)

    @classmethod
    def _deterministic_route(
        cls, content: str, employees: list[Employee]
    ) -> AgentRoute:
        text = content.strip()
        normalized = text.lower()
        known = {employee.id for employee in employees}
        normalized_text = _normalize_identifier_text(text)
        referenced_ids = {
            match.upper() for match in re.findall(
                r"(?<![A-Za-z0-9_])[eE]\d{1,4}(?![A-Za-z0-9_])",
                normalized_text,
            )
        }
        unknown = sorted(referenced_ids - known)
        if unknown:
            raise UnknownAgentEmployeeError(unknown)
        employee_ids = sorted(referenced_ids)

        reference = AgentReference()
        ordinal = re.search(r"(?:第\s*([一二两三四五六七八九十\d]+)\s*条|(?:suggestion|方案)[_ ]?(\d+))", normalized)
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
            "帮排",
            "排一版",
            "生成",
            "按这个改",
            "按第二条改",
            "replan",
            "generate",
            "能排吗",
            "这样呢",
            "重新试",
            "试排",
            "what if",
            "能排不",
            "行不行",
            "只请",
            "仅请",
            "也请",
            "取消",
            "撤销",
            "恢复可用",
            "不用请假",
            "保存当前方案",
            "采用当前方案",
            "生成正式草稿",
            "清掉",
            "清除",
            "恢复全部",
            "clear",
            "强制生成",
            "强制排",
            "即使违反规则",
        )
        mutation_requested = any(term in normalized for term in mutation_terms)
        reference_apply = reference.type != "none" and any(
            term in normalized for term in ("调整", "改", "应用", "按方案", "apply")
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
        elif any(term in normalized for term in (
            "能排吗", "能排不", "这样呢", "行不行", "重新试", "试排", "what if",
            "只请", "仅请", "也请", "取消", "撤销", "恢复可用", "不用请假",
            "清掉", "清除", "恢复全部", "clear",
        )):
            intent = AgentIntent.WHAT_IF
        elif reference_apply or any(
            term in normalized
            for term in ("重新排", "重排", "调整排班", "按这个改", "replan")
        ):
            intent = AgentIntent.REPLAN
        elif any(term in normalized for term in ("生成", "排一版", "新排班", "帮排", "保存当前方案", "采用当前方案", "生成正式草稿", "generate")):
            intent = AgentIntent.GENERATE
        elif any(term in normalized for term in ("校验", "检查排班", "违反规则", "validate")):
            intent = AgentIntent.VALIDATE
        elif any(term in normalized for term in ("为什么", "原因", "explain")):
            intent = AgentIntent.EXPLAIN
        elif any(term in normalized for term in ("建议", "优化", "影响", "advice")):
            intent = AgentIntent.ADVICE
        else:
            intent = AgentIntent.ASK

        days = IntentParser.extract_days(text)
        day = days[0] if days else None
        leave = any(term in normalized for term in (
            "请假", "请周", "只请", "仅请", "也请", "不可工作", "别排", "leave", "unavailable",
        ))
        remove_leave = any(term in normalized for term in ("取消", "撤销", "恢复可用", "不用请假", "remove"))
        leave = leave or remove_leave
        operations = cls._extract_operations(text, employee_ids, days, leave, remove_leave)
        changes = [
            ScheduleChange(employee_id=item.employee_id, type=item.type, day=item.day)
            for item in operations
            if item.day is not None
        ]
        operation = (
            "clear" if any(term in normalized for term in ("清掉", "清除", "恢复全部", "clear"))
            else "remove" if remove_leave
            else "set" if any(term in normalized for term in ("只", "仅", "only", "set"))
            else "add"
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
        explicit_force = any(term in normalized for term in (
            "强制生成", "强制排", "强制安排", "force generate", "authorized override", "即使违反规则", "我授权", "没有店长也先排", "没有店长也先生成",
        )) or (leave and any(term in normalized for term in ("还是让", "就是让", "仍然安排", "仍要安排")))
        explicit_force = explicit_force and cls._explicit_authorization(text)
        shifts = [value for value, tokens in (
            (Shift.MORNING, ("早班", "morning")),
            (Shift.EVENING, ("晚班", "evening")),
        ) if any(token in normalized for token in tokens)]
        shift = shifts[0] if len(shifts) == 1 else None
        if explicit_force and (leave or employee_ids) and (
            len(employee_ids) != 1 or len(days) != 1 or shift is None
        ):
            return AgentRoute(intent=AgentIntent.CLARIFICATION, clarification=AgentClarification(
                required=True, question="请逐条指定要强制安排的员工、日期和一个班次；不能授权整周或全部员工。"
            ))
        requested_overrides: list[OverrideScope] = []
        forced_assignments: list[Assignment] = []
        if explicit_force and len(employee_ids) == 1 and len(days) == 1 and shift is not None:
            if leave:
                requested_overrides.append(OverrideScope(
                    rule_id="R08", employee_id=employee_ids[0], day=day, shift=shift
                ))
            if any(term in normalized for term in ("上班", "安排", "让", "排到")):
                forced_assignments.append(Assignment(
                    employee_id=employee_ids[0], day=day, shift=shift
                ))
        coverage_rule = re.search(r"\br0([1-4])\b", normalized)
        shortage = re.search(r"(?:缺口|shortage)\s*(?:<=|≤|不超过|最多|上限)?\s*(\d+)", normalized)
        if explicit_force and coverage_rule and shortage and len(days) == 1 and shift is not None:
            limit = int(shortage.group(1))
            if 1 <= limit <= 100:
                requested_overrides.append(OverrideScope(rule_id=f"R0{coverage_rule.group(1)}", day=day, shift=shift, allowed_shortage=limit))
        force_generate = explicit_force
        clear_requested = operation == "clear"
        if (leave or clear_requested) and not employee_ids:
            clarification = AgentClarification(
                required=True,
                question="请说明需要调整或清空的员工编号。" if clear_requested else "请说明需要调整的员工编号。",
            )
            intent = AgentIntent.CLARIFICATION
            mutation_requested = False
        elif leave and day is None:
            clarification = AgentClarification(
                required=True, question="请说明请假或不可工作的具体日期。"
            )
            intent = AgentIntent.CLARIFICATION
            mutation_requested = False

        if force_generate:
            intent = AgentIntent.GENERATE
            mutation_requested = True
            clarification = AgentClarification()
            changes = []
            operations = []

        return AgentRoute(
            intent=intent,
            mutation_requested=mutation_requested,
            target_week=target_week,
            target_iso_year=int(iso_match.group(1)) if iso_match and iso_match.group(1) else None,
            target_iso_week=int(iso_match.group(2)) if iso_match else None,
            employees=employee_ids,
            changes=changes,
            operations=operations,
            operation=operation,
            minimize_changes=any(
                term in normalized for term in ("尽量少", "最小调整", "不要动", "minimize")
            ),
            reference=reference,
            clarification=clarification,
            override_requested=bool(requested_overrides),
            force_generate=force_generate,
            requested_overrides=requested_overrides,
            forced_assignments=forced_assignments,
            authorization_reason=text if force_generate else None,
        )

    @staticmethod
    def _extract_changes(
        text: str,
        employee_ids: list[str],
        fallback_days: list[Day],
        leave: bool,
        remove_leave: bool,
    ) -> list[ScheduleChange]:
        """Parse deterministic button-compatible input without cross-product leakage."""
        if not leave:
            return []
        normalized = _normalize_identifier_text(text)
        mentions = list(re.finditer(
            r"(?<![A-Za-z0-9_])([eE]\d{1,4})(?![A-Za-z0-9_])", normalized
        ))
        if len(mentions) <= 1:
            ids_and_spans = [(employee_ids[0], normalized)] if employee_ids else []
        else:
            ids_and_spans = []
            for index, match in enumerate(mentions):
                end = mentions[index + 1].start() if index + 1 < len(mentions) else len(normalized)
                ids_and_spans.append((match.group(1).upper(), normalized[match.start():end]))
        result: list[ScheduleChange] = []
        for employee_id, span in ids_and_spans:
            span_days = IntentParser.extract_days(span) or fallback_days
            span_remove = any(
                token in span.lower()
                for token in ("不请", "不用请假", "取消", "撤销", "恢复可用", "remove")
            )
            if len(mentions) <= 1:
                span_remove = remove_leave or span_remove
            change_type = ChangeType.AVAILABLE if span_remove else ChangeType.LEAVE
            result.extend(
                ScheduleChange(employee_id=employee_id, type=change_type, day=day)
                for day in span_days
            )
        return result

    @classmethod
    def _extract_operations(
        cls,
        text: str,
        employee_ids: list[str],
        fallback_days: list[Day],
        leave: bool,
        remove_leave: bool,
    ) -> list[AgentScenarioOperation]:
        if not leave:
            return []
        normalized = _normalize_identifier_text(text)
        mentions = list(re.finditer(
            r"(?<![A-Za-z0-9_])([eE]\d{1,4})(?![A-Za-z0-9_])", normalized
        ))
        if len(mentions) <= 1:
            ids_and_spans = [(employee_ids[0], normalized)] if employee_ids else []
        else:
            ids_and_spans = []
            for index, match in enumerate(mentions):
                end = mentions[index + 1].start() if index + 1 < len(mentions) else len(normalized)
                ids_and_spans.append((match.group(1).upper(), normalized[match.start():end]))
        result: list[AgentScenarioOperation] = []
        for employee_id, span in ids_and_spans:
            lowered = span.lower()
            span_days = IntentParser.extract_days(span) or fallback_days
            span_remove = remove_leave or any(
                token in lowered
                for token in ("不请", "不用请假", "取消", "撤销", "恢复可用", "remove")
            )
            span_clear = any(token in lowered for token in ("清掉", "清除", "恢复全部", "clear"))
            span_set = any(token in lowered for token in ("只", "仅", "only", "set", "改成"))
            operation = "clear" if span_clear else "remove" if span_remove else "set" if span_set else "add"
            change_type = ChangeType.AVAILABLE if operation == "remove" else ChangeType.LEAVE
            if operation == "clear" and not span_days:
                result.append(AgentScenarioOperation(
                    operation=operation, employee_id=employee_id, type=change_type, day=None
                ))
                continue
            result.extend(
                AgentScenarioOperation(
                    operation=operation, employee_id=employee_id, type=change_type, day=day
                )
                for day in span_days
            )
        return result
