from __future__ import annotations

import logging
import os
import re
from contextlib import nullcontext
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from ..execution import traced
from ..models import ChangeType, Day, Employee, RequestIntent, ScheduleChange, Shift
from .entity_resolver import EntityResolver
from .llm_client import AgentLLMClient

logger = logging.getLogger("optishift.intent")


class LLMIntentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: RequestIntent
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = False


def _normalize_identifier_text(value: str) -> str:
    """Normalize only identifier punctuation; preserve names and free text."""
    return value.translate(str.maketrans({
        "ｅ": "e", "Ｅ": "E",
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    }))


DAY_TOKENS = {
    Day.MON: ("mon", "monday", "周一", "星期一"),
    Day.TUE: ("tue", "tuesday", "周二", "星期二"),
    Day.WED: ("wed", "wednesday", "周三", "星期三"),
    Day.THU: ("thu", "thursday", "周四", "星期四"),
    Day.FRI: ("fri", "friday", "周五", "星期五"),
    Day.SAT: ("sat", "saturday", "周六", "星期六"),
    Day.SUN: ("sun", "sunday", "周日", "星期日", "星期天"),
}


@dataclass(frozen=True)
class ParsedIntent:
    intent: RequestIntent
    changes: list[ScheduleChange]
    minimize_changes: bool
    resolution: dict | None = None


class IntentParser:
    def __init__(self, resolver: EntityResolver | None = None, llm: AgentLLMClient | None = None) -> None:
        self.resolver = resolver or EntityResolver()
        self.llm = llm

    @staticmethod
    def extract_days(prompt: str) -> list[Day]:
        normalized = prompt.lower()
        found: list[Day] = []
        for day, tokens in DAY_TOKENS.items():
            if any(re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", normalized) if token.isascii() else token in normalized for token in tokens):
                found.append(day)
        ranges = [(Day.MON, Day.TUE, "周一到周二"), (Day.MON, Day.WED, "周一到周三"), (Day.MON, Day.THU, "周一到周四"), (Day.MON, Day.FRI, "周一到周五"), (Day.MON, Day.SAT, "周一到周六"), (Day.MON, Day.SUN, "周一到周日")]
        for start, end, token in ranges:
            if token in normalized:
                start_index = list(DAY_TOKENS).index(start)
                end_index = list(DAY_TOKENS).index(end)
                found = list(DAY_TOKENS)[start_index : end_index + 1]
                break
        return list(dict.fromkeys(found))

    @staticmethod
    def extract_day(prompt: str) -> Day | None:
        days = IntentParser.extract_days(prompt)
        return days[0] if days else None

    def parse(
        self,
        prompt: str,
        employees: list[Employee],
        *,
        default_intent: RequestIntent = RequestIntent.GENERATE,
    ) -> ParsedIntent:
        text = prompt.strip()
        normalized = _normalize_identifier_text(text).lower()
        intent = default_intent
        if any(token in normalized for token in ("replan", "重新排", "重排", "调整排班")):
            intent = RequestIntent.REPLAN
        elif any(token in normalized for token in ("validate", "校验", "检查排班")):
            intent = RequestIntent.VALIDATE

        days = self.extract_days(text)
        day = days[0] if days else None
        minimize = any(
            token in normalized
            for token in ("尽量少", "不要动", "最小调整", "minimal", "minimize", "preserve")
        )
        changes: list[ScheduleChange] = []
        leave_language = any(
            token in normalized for token in ("请假", "请周", "只请", "仅请", "别排", "不排", "不可工作", "unavailable", "leave")
        )

        explicit_ids = sorted({match.upper() for match in re.findall(
            r"(?<![A-Za-z0-9_])[eE]\d{1,4}(?![A-Za-z0-9_])",
            _normalize_identifier_text(text),
        )})
        known_ids = {employee.id for employee in employees}
        unknown = [employee_id for employee_id in explicit_ids if employee_id not in known_ids]
        if unknown:
            return ParsedIntent(
                intent=intent,
                changes=[],
                minimize_changes=minimize,
                resolution={"status": "entity_not_found", "unknown_ids": unknown},
            )

        preference_language = any(
            token in normalized for token in ("偏好", "prefer", "早班", "晚班")
        )
        if day is None and (leave_language or (explicit_ids and preference_language)):
            return ParsedIntent(
                intent=intent,
                changes=[],
                minimize_changes=minimize,
                resolution={
                    "status": "clarification_required",
                    "candidates": [],
                    "missing_fields": ["day"],
                },
            )

        if day is not None and leave_language:
            if explicit_ids:
                changes = [
                    ScheduleChange(employee_id=employee_id, type=ChangeType.LEAVE, day=item_day)
                    for employee_id in explicit_ids
                    for item_day in days
                ]
            elif any(token in normalized for token in ("所有店长", "所有经理", "all manager")):
                managers = [
                    employee
                    for employee in employees
                    if "manager" in {skill.value for skill in employee.skills}
                ]
                changes = [
                    ScheduleChange(employee_id=employee.id, type=ChangeType.LEAVE, day=item_day)
                    for employee in managers
                    for item_day in days
                ]
            elif any(token in normalized for token in ("兼职", "part-time", "part time", "那个")):
                resolution = self.resolver.resolve(text, employees, day=day).as_dict()
                if resolution["status"] == "resolved":
                    changes = [
                        ScheduleChange(
                            employee_id=resolution["employee"]["id"],
                            type=ChangeType.LEAVE,
                            day=item_day,
                        )
                        for item_day in days
                    ]
                else:
                    return ParsedIntent(intent, [], minimize, resolution)

        if day is not None and explicit_ids and preference_language:
            shift = Shift.MORNING if any(t in normalized for t in ("早班", "morning")) else Shift.EVENING
            changes.extend(
                ScheduleChange(
                    employee_id=employee_id,
                    type=ChangeType.PREFERENCE,
                    day=day,
                    shift=shift,
                )
                for employee_id in explicit_ids
                if employee_id in known_ids
            )

        deterministic = ParsedIntent(intent, changes, minimize)
        llm_enabled = (
            self.llm.enabled
            if self.llm is not None
            else (os.getenv("LLM_ENABLED", "").strip().lower() in {"1", "true", "yes"})
        )
        if not llm_enabled:
            return deterministic
        llm_result = self._parse_with_llm(text, employees, default_intent)
        if llm_result is not None:
            return llm_result
        return deterministic

    @traced("intent_parse")
    def _parse_with_llm(
        self,
        prompt: str,
        employees: list[Employee],
        default_intent: RequestIntent,
    ) -> ParsedIntent | None:
        api_key = os.getenv("LLM_API_KEY", "").strip()
        if not api_key:
            logger.info("llm_fallback_triggered reason=missing_api_key operation=intent_parse")
            return None
        employee_ids = [employee.id for employee in employees]
        schema = {
            "name": "schedule_intent",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "intent": {"type": "string", "enum": ["generate", "replan", "validate"]},
                    "changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "employee_id": {"type": "string"},
                                "type": {"type": "string", "enum": ["leave", "unavailable", "available", "preference", "assign", "unassign"]},
                                "day": {"type": "string", "enum": [day.value for day in Day]},
                                "shift": {"type": ["string", "null"], "enum": ["morning", "evening", None]},
                            },
                            "required": ["employee_id", "type", "day", "shift"],
                        },
                    },
                    "minimize_changes": {"type": "boolean"},
                },
                "required": ["intent", "changes", "minimize_changes"],
            },
        }
        try:
            with nullcontext(self.llm) if self.llm else AgentLLMClient() as client:
                payload = client.complete_json(
                    stage="intent_parse", schema_name="schedule_intent", schema=schema["schema"],
                    system="Convert the request to scheduling intent JSON. Use only supplied employee IDs. Never change skills. Return empty changes if none are requested.",
                    user={"request": prompt, "default_intent": default_intent.value,
                          "valid_employee_ids": employee_ids},
                )
            parsed = LLMIntentOutput.model_validate(payload)
            unknown = sorted({change.employee_id for change in parsed.changes} - set(employee_ids))
            if unknown:
                logger.warning("llm_output_rejected reason=unknown_employee ids=%s", unknown)
                return ParsedIntent(
                    intent=parsed.intent,
                    changes=[],
                    minimize_changes=parsed.minimize_changes,
                    resolution={"status": "entity_not_found", "unknown_ids": unknown},
                )
            return ParsedIntent(parsed.intent, parsed.changes, parsed.minimize_changes)
        except Exception as exc:
            logger.info(
                "llm_fallback_triggered reason=%s operation=intent_parse",
                type(exc).__name__,
            )
            return None
