"""Compatibility adapter for prompt-bearing schedule endpoints; uses the same TurnPlan."""
from dataclasses import dataclass, field
from ..models import RequestIntent, ScheduleChange, StaffingConstraint
from ..models.dialogue import DialogueState
from .entity_resolver import EntityResolver
from .llm_client import AgentLLMClient

@dataclass(frozen=True)
class ParsedIntent:
    intent: RequestIntent
    changes: list[ScheduleChange]
    minimize_changes: bool
    resolution: dict | None = None
    staffing_constraints: list[StaffingConstraint] = field(default_factory=list)

class IntentParser:
    def __init__(self, resolver=None, llm=None):
        self.resolver = resolver or EntityResolver()
        self.llm = llm

    def parse(self, prompt, employees, *, default_intent=RequestIntent.GENERATE, current_week_start=None):
        from .dialogue_parser import parse_command
        command = parse_command(prompt, DialogueState(), employees, self.llm or AgentLLMClient(), current_week_start=current_week_start)
        incomplete = any(not e.employee_ids or not e.days or not e.type or
            (e.type.value in {"assign", "unassign", "preference"} and not e.shift)
            or e.operation != "add" for e in command.edits)
        question = command.clarification
        if current_week_start and command.target_week and command.target_week != current_week_start:
            question = "解析出的目标周与请求目标周不同，请通过 Agent 明确目标周。"
        if (incomplete or command.suppress_execution or command.execution != "create_draft"
                or command.domain != "scheduling" or command.force_generate
                or command.reference != "none" or command.staffing_operation != "merge"):
            question = question or "请通过 Agent 对话记录、分析或补充条件；此接口只创建明确授权的草稿。"
        if question:
            return ParsedIntent(default_intent, [], False,
                {"status": "clarification_required", "question": question, "candidates": []})
        changes = [ScheduleChange(employee_id=e.employee_ids[0], day=e.days[0], type=e.type, shift=e.shift)
                   for e in command.edits]
        return ParsedIntent(default_intent, changes, command.minimize_changes,
                            staffing_constraints=command.staffing_constraints)
