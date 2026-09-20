"""A turn records conditions independently from its one-turn execution authority."""
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .domain import ChangeType, Day, ScheduleChange, Shift


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
    employee_id: str | None = None
    type: ChangeType | None = None
    days: list[Day] = Field(default_factory=list)
    shift: Shift | None = None
    source_message_id: str
    proposal: bool = False

    def missing(self):
        return [name for name, absent in (
            ("员工", not self.employee_id), ("动作", not self.type), ("日期", not self.days),
            ("班次", self.type in {ChangeType.ASSIGN, ChangeType.UNASSIGN, ChangeType.PREFERENCE} and not self.shift),
        ) if absent]


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
    minimize_changes: bool = True

    def current(self):
        items = {item.id: item for item in self.conditions + self.proposals}
        return [items[key] for key in self.context_ids if key in items]


class ConditionEdit(DialogueModel):
    operation: Literal["add", "remove", "correct", "adopt", "cancel_pending", "focus"] = "add"
    employee_ids: list[str] = Field(default_factory=list)
    days: list[Day] = Field(default_factory=list)
    shift: Shift | None = None
    type: ChangeType | None = None
    reference_ids: list[str] = Field(default_factory=list)
    proposal: bool = False
    group_skill: str | None = None
    old_day: Day | None = None


class TurnCommand(DialogueModel):
    edits: list[ConditionEdit] = Field(default_factory=list)
    execution: Literal["none", "analyze", "preview", "create_draft", "advice"] = "none"
    reference: Literal["none", "current", "active", "suggestion"] = "none"
    reference_ids: list[str] = Field(default_factory=list)
    expected_count: int | None = None
    suggestion_id: str | None = None
    suggestion_set_id: str | None = None
    suggestion_ordinal: int | None = None
    adopt: bool = False
    inspect: bool = False
    explicit_empty: bool = False
    minimize_changes: bool = False
    clarification: str | None = None
    source: str = "deterministic"
