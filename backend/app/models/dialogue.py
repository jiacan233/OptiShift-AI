"""A turn records conditions independently from its one-turn execution authority."""
from typing import Literal
from datetime import date
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import ChangeType, Day, ScheduleChange, Shift, StaffingConstraint, Assignment
from .overrides import OverrideScope
from enum import StrEnum

class AgentDomain(StrEnum):
    SCHEDULING = "scheduling"
    PRODUCT = "product"
    SMALLTALK = "smalltalk"
    OUT_OF_SCOPE = "out_of_scope"


class SpeechAct(StrEnum):
    QUESTION = "question"
    ACTION_REQUEST = "action_request"
    CAPABILITY_QUESTION = "capability_question"
    EXPLANATION_REQUEST = "explanation_request"


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





def identity():
    return uuid4().hex


class DialogueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(DialogueModel):
    id: str = Field(default_factory=identity)
    changes: list[ScheduleChange]
    source_message_id: str
    source_kind: str = "user"
    employee_revision: int | None = None
    suggestion_id: str | None = None


class PendingAction(DialogueModel):
    id: str = Field(default_factory=identity)
    kind: Literal["employee", "force_staffing"] = "employee"
    prompt: str | None = None
    staffing_constraints: list[StaffingConstraint] = Field(default_factory=list)
    requested_overrides: list[OverrideScope] = Field(default_factory=list)
    dependencies: dict = Field(default_factory=dict)
    employee_id: str | None = None
    employee_mode: Literal["UNKNOWN", "FIXED"] = "UNKNOWN"
    type: ChangeType | None = None
    type_mode: Literal["UNKNOWN", "FIXED"] = "UNKNOWN"
    days: list[Day] = Field(default_factory=list)
    candidate_days: list[Day] = Field(default_factory=list)
    day_selection_mode: Literal["UNKNOWN", "FIXED", "FLEXIBLE"] = "UNKNOWN"
    work_day_count: int | None = None
    work_day_count_mode: Literal["UNKNOWN", "FIXED", "FLEXIBLE"] = "UNKNOWN"
    shift: Shift | None = None
    shift_mode: Literal["UNKNOWN", "FIXED", "FLEXIBLE", "PREFERENCE"] = "UNKNOWN"
    source_message_id: str = ""
    proposal: bool = False
    execution_on_complete: Literal["none", "create_draft"] = "none"

    @model_validator(mode="after")
    def auto_detect_modes(self) -> "PendingAction":
        if self.employee_id and self.employee_mode == "UNKNOWN":
            self.employee_mode = "FIXED"
        if self.type and self.type_mode == "UNKNOWN":
            self.type_mode = "FIXED"
        if self.shift and self.shift_mode == "UNKNOWN":
            self.shift_mode = "FIXED"
        if self.days and self.day_selection_mode == "UNKNOWN":
            self.day_selection_mode = "FIXED"
        if self.candidate_days and self.day_selection_mode == "UNKNOWN":
            self.day_selection_mode = "FLEXIBLE"
        if self.work_day_count is not None and self.work_day_count_mode == "UNKNOWN":
            self.work_day_count_mode = "FIXED"
        return self

    def missing(self):
        if self.kind == "force_staffing":
            return ["确认违反 R04 的人数安排"]
        absent = []
        if (self.employee_mode == "UNKNOWN" and not self.employee_id) or not self.employee_id:
            absent.append("员工")
        if (self.type_mode == "UNKNOWN" and not self.type) or not self.type:
            absent.append("动作")
        if self.day_selection_mode == "UNKNOWN":
            if not self.days and not (self.candidate_days and self.work_day_count):
                absent.append("日期")
        elif self.day_selection_mode == "FIXED":
            if not self.days:
                absent.append("日期")
        elif self.day_selection_mode == "FLEXIBLE":
            if not self.candidate_days or self.work_day_count is None:
                absent.append("日期")
        if self.type in {ChangeType.ASSIGN, ChangeType.UNASSIGN, ChangeType.PREFERENCE}:
            if self.shift_mode == "UNKNOWN" and not self.shift:
                absent.append("班次")
            elif self.shift_mode == "FIXED" and not self.shift:
                absent.append("班次")
        return absent


class Focus(DialogueModel):
    kind: Literal["condition", "pending", "proposal", "employees"]
    ids: list[str]


class DialogueState(DialogueModel):
    schema_version: int = 1
    revision: int = 0
    scenario_revision: int = 0
    conditions: list[Condition] = Field(default_factory=list)
    proposals: list[Condition] = Field(default_factory=list)
    pending: list[PendingAction] = Field(default_factory=list)
    focus: Focus | None = None
    employee_focus: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    tombstones: list[str] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestion_sets: list[dict] = Field(default_factory=list)
    last_preview: dict | None = None
    last_draft: dict | None = None
    staffing_constraints: list[StaffingConstraint] = Field(default_factory=list)
    proposed_staffing: list[StaffingConstraint] | None = None
    minimize_changes: bool = True

    def current(self):
        items = {item.id: item for item in self.conditions + self.proposals}
        return [items[key] for key in self.context_ids if key in items]


class ConditionEdit(DialogueModel):
    operation: Literal["add", "remove", "correct", "adopt", "cancel_pending", "focus"] = "add"
    employee_ids: list[str] = Field(default_factory=list)
    employee_mode: Literal["UNKNOWN", "FIXED"] = "UNKNOWN"
    days: list[Day] = Field(default_factory=list)
    candidate_days: list[Day] = Field(default_factory=list)
    day_selection_mode: Literal["UNKNOWN", "FIXED", "FLEXIBLE"] = "UNKNOWN"
    work_day_count: int | None = None
    work_day_count_mode: Literal["UNKNOWN", "FIXED", "FLEXIBLE"] = "UNKNOWN"
    shift: Shift | None = None
    shift_mode: Literal["UNKNOWN", "FIXED", "FLEXIBLE", "PREFERENCE"] = "UNKNOWN"
    type: ChangeType | None = None
    type_mode: Literal["UNKNOWN", "FIXED"] = "UNKNOWN"
    reference_ids: list[str] = Field(default_factory=list)
    proposal: bool = False
    group_skill: str | None = None
    old_day: Day | None = None

    @model_validator(mode="after")
    def auto_detect_modes(self) -> "ConditionEdit":
        if self.employee_ids and self.employee_mode == "UNKNOWN":
            self.employee_mode = "FIXED"
        if self.type and self.type_mode == "UNKNOWN":
            self.type_mode = "FIXED"
        if self.shift and self.shift_mode == "UNKNOWN":
            self.shift_mode = "FIXED"
        if self.days and self.day_selection_mode == "UNKNOWN":
            self.day_selection_mode = "FIXED"
        if self.candidate_days and self.day_selection_mode == "UNKNOWN":
            self.day_selection_mode = "FLEXIBLE"
        if self.work_day_count is not None and self.work_day_count_mode == "UNKNOWN":
            self.work_day_count_mode = "FIXED"
        return self


class TurnCommand(DialogueModel):
    """The single semantic TurnPlan; downstream routes are projections only."""
    domain: AgentDomain = AgentDomain.SCHEDULING
    speech_act: SpeechAct = SpeechAct.QUESTION
    target_week: date | None = None
    mutation_requested: bool = False
    staffing_constraints: list[StaffingConstraint] = Field(default_factory=list)
    staffing_operation: Literal["merge", "replace", "clear"] = "merge"
    read_query: ReadQueryPlan | None = None
    product_topic_ids: list[str] = Field(default_factory=list)
    force_generate: bool = False
    pending_decision: Literal["none", "confirm", "cancel"] = "none"
    pending_action_id: str | None = None
    requested_overrides: list[OverrideScope] = Field(default_factory=list)
    forced_assignments: list[Assignment] = Field(default_factory=list)
    authorization_reason: str | None = None
    declared_condition_count: int = Field(default=0, ge=0)
    expected_revision: int | None = Field(default=None, ge=0)
    expected_scenario_revision: int | None = Field(default=None, ge=0)

    edits: list[ConditionEdit] = Field(default_factory=list)
    execution: Literal["none", "analyze", "preview", "create_draft", "advice"] = "none"
    suppress_execution: bool = False
    reference: Literal["none", "current", "active", "suggestion"] = "none"
    reference_ids: list[str] = Field(default_factory=list)
    expected_count: int | None = Field(default=None, ge=0, strict=True)
    suggestion_id: str | None = None
    suggestion_set_id: str | None = None
    suggestion_ordinal: int | None = Field(default=None, ge=1, strict=True)
    adopt: bool = False
    inspect: bool = False
    explicit_empty: bool = False
    minimize_changes: bool = False
    clarification: str | None = None
    source: str = "semantic_parser"
