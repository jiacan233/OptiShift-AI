from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .agent_router import AgentRoute
from ..execution import traced


class WeekResolutionError(ValueError):
    def __init__(self, question: str) -> None:
        self.question = question
        super().__init__(question)


@dataclass(frozen=True)
class ResolvedWeek:
    week_start: date
    iso_year: int
    iso_week: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_week": self.week_start.isoformat(),
            "iso_year": self.iso_year,
            "iso_week": self.iso_week,
            "resolution_source": self.source,
        }


def monday_for(value: date) -> date:
    return value - timedelta(days=value.weekday())


class WeekResolver:
    """Validate structured week references and select the stored schedule context."""

    @staticmethod
    def _message_week(message: dict[str, Any]) -> date | None:
        candidates = [
            message.get("target_week"),
            (message.get("metadata") or {}).get("target_week"),
            (message.get("metadata_json") or {}).get("target_week"),
        ]
        for value in candidates:
            if isinstance(value, date):
                return monday_for(value)
            if isinstance(value, str):
                try:
                    return monday_for(date.fromisoformat(value))
                except ValueError:
                    continue
        return None

    @classmethod
    def _previous_target(cls, messages: list[dict[str, Any]]) -> date | None:
        for message in reversed(messages):
            resolved = cls._message_week(message)
            if resolved is not None:
                return resolved
        return None

    @traced("resolve_context")
    def resolve(self, *, content, route, current_week_start, recent_messages,
                referenced_week=None, trusted_week=None, today=None):
        if route.target_iso_week is not None:
            if route.target_iso_year is None:
                raise WeekResolutionError("请补充 ISO 年份。")
            try:
                week = date.fromisocalendar(route.target_iso_year, route.target_iso_week, 1)
            except ValueError as exc:
                raise WeekResolutionError("ISO 周次无效。") from exc
            return self._result(week, "structured_iso_week")
        if route.target_week is not None:
            if route.target_week.weekday() != 0:
                raise WeekResolutionError("目标周必须是周一日期。")
            return self._result(route.target_week, "semantic_parser")
        for value, source in ((trusted_week, "trusted_action"), (referenced_week, "conversation_reference"),
                              (current_week_start, "workbench"),
                              (self._previous_target(recent_messages), "conversation_reference")):
            if value is not None:
                return self._result(monday_for(value), source)
        return self._result(monday_for(today or date.today()), "current_monday")

    @staticmethod
    def _result(week_start, source):
        iso = week_start.isocalendar()
        return ResolvedWeek(week_start, iso.year, iso.week, source)
