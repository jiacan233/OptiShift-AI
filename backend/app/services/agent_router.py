from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from threading import local
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..execution import traced
from ..models import Assignment, ChangeType, Day, Employee, OverrideScope, ScheduleChange, Shift
from .intent_parser import DAY_TOKENS, IntentParser, _normalize_identifier_text
from .read_query import ReadQueryPlan, QuestionType, explicit_reference, is_counterfactual, is_read_only_question, normalize_plan
from .router_stages import RouterRun, parse_stage, schema_bytes
from .llm_client import (
    AgentLLMClient,
    AIUnavailableError,
    strict_json_schema,
)


def calibrate_read_route(route: "AgentRoute", content: str, employees: list[Employee]) -> "AgentRoute":
    reference = explicit_reference(content)
    route.reference = AgentReference(
        type="previous_message" if reference == "previous_message" else "suggestion" if reference else "none",
        suggestion_id=reference if reference and reference != "previous_message" else None,
    )
    plan = normalize_plan(content, employees, proposal=route.read_query)
    deterministic = AgentRouter._deterministic_route(content, employees)
    if reference and re.search(r"(?:按|就用|采用|应用).*(?:条|建议|方案|suggestion)|^(?:apply|use)\b", content, re.I):
        deterministic.intent = AgentIntent.REPLAN
        deterministic.mutation_requested = True
    explicit_read = (
        not deterministic.mutation_requested and plan.question_type != "general_question"
        and not (deterministic.intent is AgentIntent.ADVICE and deterministic.changes)
        and not AgentRouter._explicit_mutation(content)
        and not AgentRouter._explicit_authorization(content)
    )
    if is_counterfactual(content) or is_read_only_question(content) or (explicit_read and route.intent is not AgentIntent.VALIDATE):
        route = route.model_copy(update={
            "intent": AgentIntent.EXPLAIN, "mutation_requested": False, "changes": [],
            "operations": [], "force_generate": False, "override_requested": False,
            "requested_overrides": [], "forced_assignments": [],
            "clarification": AgentClarification(),
        })
    if reference and not deterministic.mutation_requested:
        route.intent = AgentIntent.EXPLAIN
        route.mutation_requested = False
    if reference and deterministic.mutation_requested:
        route.intent = deterministic.intent
        route.mutation_requested = True
    if route.intent in {AgentIntent.ASK, AgentIntent.EXPLAIN, AgentIntent.ADVICE, AgentIntent.VALIDATE} and not route.changes:
        route.read_query = plan
        route.employees = plan.employee_ids
        route.target_week = None
        route.target_iso_year = None
        route.target_iso_week = None
        if plan.clarification:
            route.intent = AgentIntent.CLARIFICATION
            route.mutation_requested = False
            route.clarification = AgentClarification(required=True, question=plan.clarification)
    elif route.intent in {AgentIntent.GENERATE, AgentIntent.REPLAN, AgentIntent.WHAT_IF}:
        route.read_query = None
    return route


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
    read_query: ReadQueryPlan | None = None
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


class RouterDecision(BaseModel):
    """Internal hints only; none of these fields authorize business execution."""
    model_config = ConfigDict(extra="forbid")
    intent: AgentIntent
    mutation_requested: bool
    employees: list[str]
    force_or_override_intent: bool
    clarification_required: bool
    question_type: QuestionType


class MutationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operations: list[AgentScenarioOperation]
    minimize_changes: bool
    clarification: str | None


class ForcePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_overrides: list[OverrideScope]
    forced_assignments: list[Assignment]
    clarification: str | None


def lite_router_json_schema() -> dict[str, Any]:
    return strict_json_schema(RouterDecision.model_json_schema())


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
        self._local = local()

    @property
    def last_run(self) -> RouterRun | None:
        return getattr(self._local, "run", None)

    @traced("agent_route")
    def route(
        self, content: str, *, employees: list[Employee], recent_messages: list[dict[str, Any]],
        conversation_summary: str | None = None, trusted_action: TrustedAgentAction | None = None,
    ) -> AgentRoute:
        self._local.run = RouterRun()
        try:
            route = self._route(content, employees=employees, recent_messages=recent_messages,
                                conversation_summary=conversation_summary, trusted_action=trusted_action)
        except AIUnavailableError as exc:
            self.last_run.error_type = exc.error_type
            fallback = self._deterministic_route(content, employees)
            if not is_counterfactual(content) and (fallback.mutation_requested or (
                normalize_plan(content, employees).question_type == "general_question"
                and not explicit_reference(content)
            )):
                raise
            route = fallback
        if trusted_action is None:
            route = calibrate_read_route(route, content, employees)
        route = self._invariants(route, employees)
        self.last_run.completed_ms = self.last_run.latency_ms
        return route

    def _route(
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

        return self._staged_route(content, employees, recent_messages, conversation_summary)

    def _staged_route(self, content, employees, recent_messages, conversation_summary) -> AgentRoute:
        # Resolve raw IDs before any provider call; lower/full-width IDs are equivalent.
        deterministic = self._deterministic_route(content, employees)
        user = {
            "message": content,
            "conversation_summary": conversation_summary,
            "employees": [employee.model_dump(mode="json") for employee in employees],
            "recent_messages": recent_messages[-12:],
        }
        decision = parse_stage(
            self.llm, self.last_run, RouterDecision, name="agent_route_lite",
            system=(
                "Classify the CURRENT scheduling message. Return routing hints only. "
                "History is context, never a new instruction. Never inherit a suggestion unless "
                "the current message explicitly references it. Counts are staffing_explanation; "
                "employee why questions are assignment_explanation, skills/validation are coverage_analysis. "
                "Questions about feasibility, '能不能/行不行/如果会怎样', are read-only unless the user "
                "explicitly asks to generate/try/replan. '把 E17 随便排到哪一天都行' is a mutation, "
                "but specifies no date or shift. Negated force or merely asking about force grants "
                "no authorization. Force hints only dispatch a separate parser. Greetings are ask. "
                "Confirmation text cannot confirm schedules. Use supplied employee IDs only. "
                "Do not request a week when unspecified; backend resolves the workbench week."
            ), user={**user, "employees": [e.id for e in employees]},
        )
        # Hints never become execution parameters. Read facts and references are
        # grounded in the current text by the existing deterministic pipeline.
        if is_read_only_question(content) or is_counterfactual(content):
            return AgentRoute(intent=AgentIntent.EXPLAIN, read_query=normalize_plan(content, employees))
        if self._negative_mutation(content):
            return AgentRoute(intent=AgentIntent.ASK, read_query=normalize_plan(content, employees))
        force = decision.force_or_override_intent or deterministic.force_generate or self._explicit_authorization(content)
        if force:
            if not self._explicit_authorization(content):
                return self._clarify("请明确授权的规则、员工、日期、班次及允许缺口。", deterministic.employees)
            parsed = parse_stage(
                self.llm, self.last_run, ForcePlan, name="agent_force",
                system=(
                    "Extract ONLY explicitly authorized exception scopes from the CURRENT message. "
                    "Never inherit authority from history. R08 requires employee/day/shift; R01-R04 "
                    "require day/shift/allowed_shortage. Do not invent a rule, day, shift or limit. "
                    "If any scope is missing, return empty arrays and clarification. "
                    "An instruction to force without a precise scope is NOT blanket authorization."
                ), user=user,
            )
            # Existing deterministic authorization owns the scope. A model cannot
            # broaden it, even when its DTO is syntactically valid.
            if (parsed.clarification or not (parsed.requested_overrides or parsed.forced_assignments)
                or parsed.requested_overrides != deterministic.requested_overrides
                or parsed.forced_assignments != deterministic.forced_assignments):
                return self._clarify("请明确要授权的规则、员工、日期、班次及允许缺口。", deterministic.employees)
            return self._validate_force_route(deterministic)

        if deterministic.intent == AgentIntent.ADVICE and deterministic.changes and not self._explicit_mutation(content):
            return deterministic
        wants_mutation = decision.mutation_requested or deterministic.mutation_requested or self._explicit_mutation(content)
        if wants_mutation:
            # A fallback or a confident model is not sufficient permission to write.
            if not self._explicit_mutation(content) and not deterministic.mutation_requested:
                return self._clarify("请明确是否需要生成、重新排班或修改试排条件。", deterministic.employees)
            parsed = parse_stage(
                self.llm, self.last_run, MutationPlan, name="agent_mutation",
                system=(
                    "Parse scheduling changes from the ORIGINAL CURRENT message, not router hints. "
                    "Preserve every employee/day and ordered add/set/remove/clear operation. "
                    "Do not form a cross-product across employees' separate clauses. '先清掉 E01 的限制，再给 E02 周五请假' "
                    "is clear E01 with day=null, then add E02 leave Fri. '周一周二请假' needs two operations. "
                    "Preference/assign/unassign require an explicit shift; all non-clear operations need a day. "
                    "Never invent unspecified days/shifts, including '随便排到哪一天'. Return clarification "
                    "when execution fields are missing. Pure schedule generation needs empty operations. "
                    "Read original text, employee master data and context; never inherit changes implicitly. "
                    "No force authorization, confirmation, read query or dates belong in this DTO."
                ), user=user,
            )
            if parsed.clarification:
                return self._clarify(parsed.clarification, deterministic.employees)
            if not self._grounded_operations(parsed.operations, content, deterministic.employees):
                return self._clarify("请逐条说明员工、日期、班次和变更类型；不会补齐未指定的条件。", deterministic.employees)
            if deterministic.employees and not parsed.operations and not explicit_reference(content):
                return self._clarify("请补充要安排的日期和班次，或说明该员工的具体变更。", deterministic.employees)
            try:
                changes = [ScheduleChange(employee_id=o.employee_id, type=o.type, day=o.day, shift=o.shift)
                           for o in parsed.operations if o.operation != "clear"]
            except ValidationError:
                return self._clarify("请补充每条变更的日期及需要的班次。", deterministic.employees)
            intent = deterministic.intent if deterministic.intent in {AgentIntent.GENERATE, AgentIntent.REPLAN, AgentIntent.WHAT_IF} else decision.intent
            if intent not in {AgentIntent.GENERATE, AgentIntent.REPLAN, AgentIntent.WHAT_IF}:
                intent = AgentIntent.WHAT_IF if parsed.operations else AgentIntent.GENERATE
            return AgentRoute(
                intent=intent, mutation_requested=True, employees=deterministic.employees,
                target_week=deterministic.target_week, target_iso_year=deterministic.target_iso_year,
                target_iso_week=deterministic.target_iso_week, operations=parsed.operations,
                changes=changes, minimize_changes=parsed.minimize_changes,
                operation=parsed.operations[0].operation if parsed.operations else "add",
            )
        intent = decision.intent
        if intent in {AgentIntent.GENERATE, AgentIntent.REPLAN, AgentIntent.WHAT_IF, AgentIntent.CLARIFICATION}:
            return self._clarify("请说明希望查询排班，还是生成或调整一版草稿。", deterministic.employees)
        return AgentRoute(intent=intent, read_query=normalize_plan(
            content, employees, proposal={"question_type": decision.question_type}
        ))

    @staticmethod
    def _clarify(question: str, employees: list[str]) -> AgentRoute:
        return AgentRoute(intent=AgentIntent.CLARIFICATION, employees=employees,
                          clarification=AgentClarification(required=True, question=question))

    @staticmethod
    def _negative_mutation(content: str) -> bool:
        return bool(re.search(r"(?:不要|别|不必|不想|不能).{0,4}(?:强制|生成|重排|违反)|do not (?:force|generate)|don't (?:force|generate)", content, re.I))

    @classmethod
    def _explicit_mutation(cls, content: str) -> bool:
        if cls._negative_mutation(content) or is_read_only_question(content):
            return False
        return bool(re.search(
            r"重新排|重排|试排|生成|给我出一版|帮我.*排|就这么排|排一版|排出来|排到|清掉|清除|撤销|取消|恢复可用|"
            r"(?:按|采用|应用).*(?:建议|条|方案)|(?:replan|generate|clear|apply)\b", content, re.I
        ))

    @staticmethod
    def _grounded_operations(operations, content, employee_ids) -> bool:
        spans: dict[str, list[str]] = {}
        for employee_id, span in AgentRouter._employee_spans(content):
            spans.setdefault(employee_id, []).append(span)
        for item in operations:
            item.employee_id = _normalize_identifier_text(item.employee_id).upper()
            if item.employee_id not in employee_ids:
                return False
            valid = False
            for span in spans.get(item.employee_id, []):
                if item.operation == "clear":
                    valid |= bool(re.search(r"清掉|清除|恢复全部|clear", span, re.I)) and (item.day is None or item.day in IntentParser.extract_days(span))
                    continue
                if item.day is None or item.day not in IntentParser.extract_days(span):
                    continue
                if item.shift and not any(t in span.lower() for t in (
                    ("早班", "morning") if item.shift == Shift.MORNING else ("晚班", "evening")
                )):
                    continue
                type_terms = {
                    ChangeType.LEAVE: r"请假|请周|只请|仅请|也请|leave",
                    ChangeType.UNAVAILABLE: r"不可|不排|别排|unavailable",
                    ChangeType.AVAILABLE: r"恢复|取消|撤销|不请|不用请假|available|remove",
                    ChangeType.PREFERENCE: r"优先|偏好|prefer",
                    ChangeType.ASSIGN: r"安排|排到|上班|assign",
                    ChangeType.UNASSIGN: r"去掉|移除|不排|别排|unassign|remove",
                }
                if not re.search(type_terms[item.type], span, re.I):
                    continue
                if item.operation == "remove" and not re.search(r"取消|撤销|恢复|不请|不用请假|remove", span, re.I):
                    continue
                if item.operation == "set" and not re.search(r"只|仅|改成|设为|only|set", span, re.I):
                    continue
                valid = True
            if not valid:
                return False
        # Independently parsed explicit conditions cannot silently disappear.
        expected = AgentRouter._extract_operations(content, employee_ids, [], False, False)
        def key(o):
            # The scenario reducer clears all conditions for this employee;
            # change type is a required DTO placeholder, not a clear scope.
            if o.operation == "clear":
                return (o.operation, o.employee_id, None, o.day, o.shift)
            return (o.operation, o.employee_id, o.type, o.day, o.shift)
        if expected and [key(o) for o in operations] != [key(o) for o in expected]:
            return False
        return not operations or set(employee_ids) <= {o.employee_id for o in operations}

    @classmethod
    def _invariants(cls, route, employees):
        known = {e.id for e in employees}
        referenced = set(route.employees) | {o.employee_id for o in route.operations} | {c.employee_id for c in route.changes}
        referenced |= {a.employee_id for a in route.forced_assignments}
        referenced |= {s.employee_id for s in route.requested_overrides if s.employee_id}
        if referenced - known:
            raise UnknownAgentEmployeeError(sorted(referenced - known))
        if route.clarification.required or route.intent == AgentIntent.CLARIFICATION:
            return cls._clarify(route.clarification.question or "请补充具体排班要求。", route.employees)
        if route.intent not in {AgentIntent.GENERATE, AgentIntent.REPLAN, AgentIntent.WHAT_IF}:
            # ADVICE may retain hypothetical changes for read-only analysis.
            return route.model_copy(update={"mutation_requested": False, "operations": [], "operation": "add",
                "force_generate": False, "override_requested": False, "requested_overrides": [],
                "forced_assignments": [], "authorization_reason": None})
        return cls._validate_force_route(route)

    def probe(self, *, employees: list[Employee]) -> dict[str, Any]:
        result = {"model": self.llm.model, "schema_name": "agent_route_lite",
                  "schema_bytes": schema_bytes(lite_router_json_schema()), "fallback_used": False,
                  "error_type": None}
        try:
            if not self.llm.enabled:
                raise AIUnavailableError("AI 功能当前未启用。", error_type="llm_disabled")
            route = self.route("把 E17 随便排到哪一天都行", employees=employees, recent_messages=[])
            run = self.last_run
            decision = run.results.get("agent_route_lite", {})
            if run.error_type or not decision.get("mutation_requested") or "E17" not in route.employees or route.changes or route.forced_assignments:
                raise AIUnavailableError("Agent Router 探针未能安全解析请求。", error_type=run.error_type or "router_probe_failed")
            result.update(status="ok", intent=route.intent.value, mutation_requested=route.mutation_requested)
        except (AIUnavailableError, UnknownAgentEmployeeError) as exc:
            result.update(status="error", error_type=getattr(exc, "error_type", "unknown_employee"))
        run = self.last_run
        result.update(latency_ms=run.latency_ms if run else 0, fallback_used=run.fallback_used if run else False)
        return result

    @staticmethod
    def _explicit_authorization(content: str) -> bool:
        if is_read_only_question(content) or re.search(r"我只是问|能否|可以.*强制.*吗|别违反规则|不要违反规则", content):
            return False
        return any(term in content.lower() for term in (
            "强制", "我授权", "允许", "即使", "还是让", "就是让", "仍然安排", "仍要安排",
            "没有店长也先", "规则先不", "限制先不", "force", "authorize", "override",
            "我知道有冲突", "有冲突也", "即使违反", "照这样排", "照样排", "照这样安排",
            "我知道", "明知", "就算违反", "违反规则也",
        )) and not any(term in content.lower() for term in (
            "不要强制", "别强制", "不能强制", "不授权", "不允许", "不强制",
            "do not override", "don't override", "do not force", "don't force",
        ))

    @staticmethod
    def _validate_force_route(route: AgentRoute) -> AgentRoute:
        if not (route.force_generate or route.override_requested or route.requested_overrides or route.forced_assignments):
            return route
        if not route.force_generate or not route.authorization_reason or not (route.requested_overrides or route.forced_assignments):
            return AgentRouter._clarify("请明确要授权的规则、具体日期和班次；请假或不可用例外还需要员工编号。", route.employees)
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

        if is_read_only_question(content) or is_counterfactual(content) or cls._negative_mutation(content):
            return AgentRoute(intent=AgentIntent.EXPLAIN if is_read_only_question(content) or is_counterfactual(content) else AgentIntent.ASK,
                              employees=employee_ids, read_query=normalize_plan(content, employees))

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
        mutation_requested = any(term in normalized for term in mutation_terms) or cls._explicit_mutation(content)
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
            ScheduleChange(employee_id=item.employee_id, type=item.type, day=item.day, shift=item.shift)
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
        iso_match = re.search(r"(?<![A-Za-z0-9_])(?:(\d{4})\s*年\s*)?(?:第\s*)?(\d{1,2})\s*周", text)
        if iso_match is None:
            iso_match = re.search(
                r"(?:(\d{4})\s*[-/]?\s*)?\b(?:week|wk)\s*(\d{1,2})\b",
                text,
                re.IGNORECASE,
            )

        clarification = AgentClarification()
        explicit_force = any(term in normalized for term in (
            "强制生成", "强制排", "强制安排", "force generate", "authorized override", "即使违反规则", "我授权", "没有店长也先排", "没有店长也先生成",
            "即使违反", "强制", "我知道有冲突", "有冲突也", "照这样排", "照样排", "照这样安排", "就算违反", "违反规则也",
        )) or (leave and any(term in normalized for term in ("还是让", "就是让", "仍然安排", "仍要安排")))
        explicit_force = explicit_force and cls._explicit_authorization(text)
        shifts = [value for value, tokens in (
            (Shift.MORNING, ("早班", "morning")),
            (Shift.EVENING, ("晚班", "evening")),
        ) if any(token in normalized for token in tokens)]
        shift = shifts[0] if len(shifts) == 1 else None
        is_r08 = leave or "r08" in normalized or "请假" in normalized or "不可工作" in normalized
        if explicit_force and (is_r08 or employee_ids) and (
            len(employee_ids) != 1 or len(days) != 1 or shift is None
        ):
            return AgentRoute(intent=AgentIntent.CLARIFICATION, clarification=AgentClarification(
                required=True, question="请逐条指定要强制安排的员工、日期和一个班次；不能授权整周或全部员工。"
            ))
        requested_overrides: list[OverrideScope] = []
        forced_assignments: list[Assignment] = []
        if explicit_force and len(employee_ids) == 1 and len(days) == 1 and shift is not None:
            if is_r08:
                requested_overrides.append(OverrideScope(
                    rule_id="R08", employee_id=employee_ids[0], day=day, shift=shift
                ))
            if any(term in normalized for term in ("上班", "安排", "让", "排到", "强制", "排班", "生成")):
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

        if mutation_requested and intent == AgentIntent.ASK:
            intent = AgentIntent.WHAT_IF if operations else AgentIntent.GENERATE
        if mutation_requested and employee_ids and not operations and not force_generate and reference.type == "none":
            return cls._clarify("请补充具体日期、班次或该员工的变更条件。", employee_ids)
        return cls._validate_force_route(AgentRoute(
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
        ))

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

    @staticmethod
    def _employee_spans(text: str) -> list[tuple[str, str]]:
        normalized = _normalize_identifier_text(text)
        mentions = list(re.finditer(r"(?<![A-Za-z0-9_])([eE]\d{1,4})(?![A-Za-z0-9_])", normalized))
        spans = []
        for index, match in enumerate(mentions):
            previous = mentions[index - 1].end() if index else 0
            separators = list(re.finditer(r"[，,；;。]", normalized[previous:match.start()]))
            start = previous + separators[-1].end() if separators else previous
            end = mentions[index + 1].start() if index + 1 < len(mentions) else len(normalized)
            # A verb preceding the NEXT employee belongs to that next clause.
            next_separator = re.search(r"[，,；;。]", normalized[match.end():end])
            if next_separator:
                end = match.end() + next_separator.start()
            spans.append((match.group(1).upper(), normalized[start:end]))
        return spans

    @classmethod
    def _extract_operations(
        cls, text: str, employee_ids: list[str], fallback_days: list[Day],
        leave: bool, remove_leave: bool,
    ) -> list[AgentScenarioOperation]:
        result = []
        for employee_id, span in cls._employee_spans(text):
            lowered = span.lower()
            days = IntentParser.extract_days(span)
            clear = bool(re.search(r"清掉|清除|恢复全部|clear", lowered))
            remove = bool(re.search(r"取消|撤销|恢复可用|不用请假|不请|remove", lowered))
            operation = "clear" if clear else "remove" if remove else "set" if re.search(r"只|仅|only|set|改成", lowered) else "add"
            if clear:
                result.extend(AgentScenarioOperation(operation="clear", employee_id=employee_id, day=d)
                              for d in (days or [None]))
                continue
            shift = Shift.MORNING if re.search(r"早班|morning", lowered) else Shift.EVENING if re.search(r"晚班|evening", lowered) else None
            change_type = (
                ChangeType.AVAILABLE if remove else
                ChangeType.LEAVE if re.search(r"请假|请周|只请|仅请|也请|leave", lowered) else
                ChangeType.UNAVAILABLE if re.search(r"不可工作|别排|unavailable", lowered) else
                ChangeType.PREFERENCE if re.search(r"偏好|优先|prefer", lowered) else
                ChangeType.ASSIGN if re.search(r"安排|排到|上班|assign", lowered) and shift else None
            )
            if change_type is None or (change_type in {ChangeType.PREFERENCE, ChangeType.ASSIGN} and shift is None):
                continue
            result.extend(AgentScenarioOperation(operation=operation, employee_id=employee_id,
                type=change_type, day=day, shift=shift if change_type in {ChangeType.PREFERENCE, ChangeType.ASSIGN} else None)
                for day in days)
        return result
