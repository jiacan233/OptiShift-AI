from __future__ import annotations
from datetime import date
from enum import StrEnum
from threading import local
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field
from ..models import Assignment, ChangeType, Day, Employee, OverrideScope, ScheduleChange, Shift, StaffingConstraint
from ..models.dialogue import TurnCommand, DialogueState
from .read_query import ReadQueryPlan
from .turn_semantics import AgentDomain, SpeechAct
from .llm_client import AgentLLMClient, AIUnavailableError, strict_json_schema
from .router_stages import RouterRun, schema_bytes
from ..execution import traced


def calibrate_read_route(route, content, employees):
    """Compatibility boundary: validate structure without reinterpreting prose."""
    return AgentRouter._invariants(route, employees)


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
    domain: AgentDomain = AgentDomain.SCHEDULING
    speech_act: SpeechAct = SpeechAct.QUESTION
    classification_source: str = "deterministic"
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
    staffing_constraints: list[StaffingConstraint] = Field(default_factory=list)
    turn_plan: TurnCommand | None = None
    product_topic_ids: list[str] = Field(default_factory=list)


class TrustedAgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["generate", "replan", "validate", "advice"]
    staffing_constraints: list[StaffingConstraint] = Field(default_factory=list)
    suggestion_id: str | None = None
    suggestion_set_id: str | None = None
    execution: Literal["record", "preview", "create_draft"] | None = None
    target_week: date | None = None
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = True
    override_requested: bool = False
    force_generate: bool = False
    requested_overrides: list[OverrideScope] = Field(default_factory=list)
    forced_assignments: list[Assignment] = Field(default_factory=list)
    authorization_reason: str | None = Field(default=None, max_length=2000)


class AgentRouter:
    def __init__(self, llm=None):
        self.llm = llm or AgentLLMClient()
        self._local = local()

    @property
    def last_run(self):
        return getattr(self._local, "run", None)

    @traced("agent_route")
    def route(self, content, *, employees, recent_messages, conversation_summary=None,
              trusted_action=None, command=None, run=None, current_week_start=None):
        self._local.run = run or RouterRun()
        if trusted_action is not None:
            a = trusted_action
            route = AgentRoute(intent=AgentIntent(a.intent), mutation_requested=a.intent in {"generate", "replan"},
                target_week=a.target_week, changes=a.changes, staffing_constraints=a.staffing_constraints,
                minimize_changes=a.minimize_changes, force_generate=a.force_generate,
                override_requested=a.override_requested, requested_overrides=a.requested_overrides,
                forced_assignments=a.forced_assignments, authorization_reason=a.authorization_reason,
                reference=AgentReference(type="suggestion" if a.suggestion_id else "none", suggestion_id=a.suggestion_id),
                classification_source="trusted_action", speech_act=SpeechAct.ACTION_REQUEST)
        else:
            if command is None:
                from .dialogue_parser import parse_command
                command = parse_command(content, DialogueState(), employees, self.llm,
                    recent_messages=recent_messages, run=self.last_run, current_week_start=current_week_start)
            route = self.from_command(command)
        self.last_run.completed_ms = self.last_run.latency_ms
        return self._invariants(route, employees)

    @staticmethod
    def from_command(command):
        intent = {"none": AgentIntent.ASK, "analyze": AgentIntent.EXPLAIN,
                  "preview": AgentIntent.WHAT_IF, "create_draft": AgentIntent.GENERATE,
                  "advice": AgentIntent.ADVICE}[command.execution]
        if command.domain == AgentDomain.OUT_OF_SCOPE:
            intent = AgentIntent.OUT_OF_SCOPE
        if command.clarification:
            intent = AgentIntent.CLARIFICATION
        suggestion_id = command.suggestion_id
        if not suggestion_id and command.suggestion_ordinal:
            suggestion_id = f"suggestion_{command.suggestion_ordinal}"
        return AgentRoute(intent=intent, domain=command.domain, speech_act=command.speech_act,
            classification_source="semantic_parser", turn_plan=command,
            target_week=command.target_week, read_query=command.read_query,
            mutation_requested=command.execution == "create_draft" and not command.suppress_execution,
            employees=sorted({e for edit in command.edits for e in edit.employee_ids}),
            staffing_constraints=command.staffing_constraints, minimize_changes=command.minimize_changes,
            force_generate=command.force_generate, override_requested=bool(command.requested_overrides),
            requested_overrides=command.requested_overrides, forced_assignments=command.forced_assignments,
            authorization_reason=command.authorization_reason, product_topic_ids=command.product_topic_ids,
            reference=AgentReference(type="suggestion" if command.reference == "suggestion" else "none",
                                     suggestion_id=suggestion_id),
            clarification=AgentClarification(required=bool(command.clarification), question=command.clarification))

    @staticmethod
    def _invariants(route, employees):
        known = {e.id for e in employees}
        referenced = set(route.employees) | {c.employee_id for c in route.changes}
        referenced |= {o.employee_id for o in route.operations} | {a.employee_id for a in route.forced_assignments}
        referenced |= {s.employee_id for s in route.requested_overrides if s.employee_id}
        if route.read_query:
            referenced |= set(route.read_query.employee_ids)
        if referenced - known:
            raise UnknownAgentEmployeeError(sorted(referenced - known))
        if route.domain != AgentDomain.SCHEDULING or route.clarification.required:
            route.mutation_requested = False
        if route.force_generate and (not route.authorization_reason or not (route.requested_overrides or route.forced_assignments)):
            return AgentRoute(intent=AgentIntent.CLARIFICATION,
                clarification=AgentClarification(required=True, question="请明确授权规则、员工、日期、班次和缺口。"))
        return route

    def probe(self, *, employees):
        try:
            route = self.route("查看当前排班", employees=employees, recent_messages=[])
            return {"status": "ok", "model": self.llm.model, "schema_name": "agent_semantic",
                    "schema_bytes": schema_bytes(agent_route_json_schema()), "intent": route.intent.value,
                    "mutation_requested": route.mutation_requested, "fallback_used": False,
                    "latency_ms": self.last_run.latency_ms, "error_type": None}
        except AIUnavailableError as exc:
            return {"status": "error", "model": self.llm.model, "error_type": exc.error_type}


def agent_route_json_schema():
    return strict_json_schema(TurnCommand.model_json_schema())


def lite_router_json_schema():
    return agent_route_json_schema()
