from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..models import ChangeType, Day, Employee, RequestIntent, ScheduleChange, Shift
from .entity_resolver import EntityResolver


logger = logging.getLogger("optishift.intent")


class LLMIntentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: RequestIntent
    changes: list[ScheduleChange] = Field(default_factory=list)
    minimize_changes: bool = False


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
    def __init__(self, resolver: EntityResolver | None = None) -> None:
        self.resolver = resolver or EntityResolver()

    @staticmethod
    def extract_day(prompt: str) -> Day | None:
        normalized = prompt.lower()
        for day, tokens in DAY_TOKENS.items():
            if any(token in normalized for token in tokens):
                return day
        return None

    def parse(
        self,
        prompt: str,
        employees: list[Employee],
        *,
        default_intent: RequestIntent = RequestIntent.GENERATE,
    ) -> ParsedIntent:
        text = prompt.strip()
        normalized = text.lower()
        intent = default_intent
        if any(token in normalized for token in ("replan", "重新排", "重排", "调整排班")):
            intent = RequestIntent.REPLAN
        elif any(token in normalized for token in ("validate", "校验", "检查排班")):
            intent = RequestIntent.VALIDATE

        day = self.extract_day(text)
        minimize = any(
            token in normalized
            for token in ("尽量少", "不要动", "最小调整", "minimal", "minimize", "preserve")
        )
        changes: list[ScheduleChange] = []
        leave_language = any(
            token in normalized for token in ("请假", "别排", "不排", "不可工作", "unavailable", "leave")
        )

        explicit_ids = sorted(
            {match.upper() for match in re.findall(r"\b[eE]\d{1,4}\b", text)}
        )
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
                    ScheduleChange(employee_id=employee_id, type=ChangeType.LEAVE, day=day)
                    for employee_id in explicit_ids
                ]
            elif any(token in normalized for token in ("所有店长", "所有经理", "all manager")):
                managers = [
                    employee
                    for employee in employees
                    if "manager" in {skill.value for skill in employee.skills}
                ]
                changes = [
                    ScheduleChange(employee_id=employee.id, type=ChangeType.LEAVE, day=day)
                    for employee in managers
                ]
            elif any(token in normalized for token in ("兼职", "part-time", "part time", "那个")):
                resolution = self.resolver.resolve(text, employees, day=day).as_dict()
                if resolution["status"] == "resolved":
                    changes = [
                        ScheduleChange(
                            employee_id=resolution["employee"]["id"],
                            type=ChangeType.LEAVE,
                            day=day,
                        )
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
        if changes or os.getenv("LLM_ENABLED", "").lower() not in {"1", "true", "yes"}:
            return deterministic
        llm_result = self._parse_with_llm(text, employees, default_intent)
        return llm_result or deterministic

    @staticmethod
    def _parse_with_llm(
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
            response = httpx.post(
                f"{os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": os.getenv("LLM_MODEL", "gpt-4.1-mini"),
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Convert the request to scheduling intent JSON. Use only the supplied "
                                "employee IDs. Never add or change skills. If no concrete change is stated, "
                                "return an empty changes array."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "request": prompt,
                                    "default_intent": default_intent.value,
                                    "valid_employee_ids": employee_ids,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    "response_format": {"type": "json_schema", "json_schema": schema},
                },
                timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "5")),
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = LLMIntentOutput.model_validate_json(content)
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
