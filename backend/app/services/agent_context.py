from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .agent_router import AgentRoute


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
    """Resolve human week references to the Monday date used by schedule storage."""

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

    @staticmethod
    def _explicit_date(content: str, baseline: date | None) -> date | None:
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", content)
        if match:
            try:
                return date.fromisoformat(match.group(1))
            except ValueError as exc:
                raise WeekResolutionError("日期格式无效，请提供有效日期。") from exc
        match = re.search(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)", content)
        if match:
            explicit_year = int(match.group(1)) if match.group(1) else None
            if explicit_year is not None:
                try:
                    return date(explicit_year, int(match.group(2)), int(match.group(3)))
                except ValueError as exc:
                    raise WeekResolutionError("日期无效，请重新说明目标日期。") from exc
            if baseline is None:
                raise WeekResolutionError("请补充日期所属年份。")
            candidates: list[date] = []
            for year in (baseline.year - 1, baseline.year, baseline.year + 1):
                try:
                    candidates.append(date(year, int(match.group(2)), int(match.group(3))))
                except ValueError:
                    continue
            if not candidates:
                raise WeekResolutionError("日期无效，请重新说明目标日期。")
            candidates.sort(key=lambda value: abs((value - baseline).days))
            if (
                len(candidates) > 1
                and abs((candidates[0] - baseline).days)
                == abs((candidates[1] - baseline).days)
            ):
                raise WeekResolutionError("目标日期可能跨年，请补充日期所属年份。")
            return candidates[0]
        return None

    @staticmethod
    def _has_explicit_week_reference(content: str) -> bool:
        """Require user text evidence before accepting model-normalized week fields."""

        return bool(
            re.search(
                r"(?:\b\d{4}-\d{1,2}-\d{1,2}\b|"
                r"(?:\d{4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)|"
                r"(?<![A-Za-z0-9])(?:\d{4}\s*年\s*)?(?:第\s*)?\d{1,2}\s*周|"
                r"\b(?:week|wk)\s*\d{1,2}\b)",
                content,
                re.IGNORECASE,
            )
        )

    def resolve(
        self,
        *,
        content: str,
        route: AgentRoute,
        current_week_start: date | None,
        recent_messages: list[dict[str, Any]],
        referenced_week: date | None = None,
        trusted_week: date | None = None,
        today: date | None = None,
    ) -> ResolvedWeek:
        previous = self._previous_target(recent_messages)
        workbench = monday_for(current_week_start) if current_week_start else None
        trusted = monday_for(trusted_week) if trusted_week is not None else None
        baseline = trusted or referenced_week or previous or workbench

        explicit_date = self._explicit_date(content, baseline)
        if explicit_date is not None:
            return self._result(monday_for(explicit_date), "explicit_date")

        iso_match = re.search(
            r"(?<![A-Za-z0-9_])(?:(\d{4})\s*年\s*)?(?:第\s*)?(\d{1,2})\s*周", content
        )
        if iso_match is None:
            iso_match = re.search(
                r"(?:(\d{4})\s*[-/]?\s*)?\b(?:week|wk)\s*(\d{1,2})\b",
                content,
                re.IGNORECASE,
            )
        if iso_match:
            iso_year = int(iso_match.group(1)) if iso_match.group(1) else None
            requested_week = int(iso_match.group(2))
            if requested_week < 1 or requested_week > 53:
                raise WeekResolutionError("ISO 周次无效，请重新说明目标周。")
            if iso_year is None:
                if baseline is None:
                    raise WeekResolutionError("请说明目标周所属的 ISO 年份。")
                baseline_iso = baseline.isocalendar()
                if abs(requested_week - baseline_iso.week) > 26:
                    raise WeekResolutionError(
                        "目标周可能跨越 ISO 年份，请补充周次所属年份。"
                    )
                iso_year = baseline_iso.year
            try:
                return self._result(
                    date.fromisocalendar(iso_year, requested_week, 1),
                    "explicit_iso_week",
                )
            except ValueError as exc:
                raise WeekResolutionError("ISO 周次无效，请重新说明目标周。") from exc

        if self._has_explicit_week_reference(content):
            if route.target_iso_week is not None:
                if route.target_iso_week < 1 or route.target_iso_week > 53:
                    raise WeekResolutionError("ISO 周次无效，请重新说明目标周。")
                iso_year = route.target_iso_year
                if iso_year is None:
                    if baseline is None:
                        raise WeekResolutionError("请说明目标周所属的 ISO 年份。")
                    baseline_iso = baseline.isocalendar()
                    if abs(route.target_iso_week - baseline_iso.week) > 26:
                        raise WeekResolutionError(
                            "目标周可能跨越 ISO 年份，请补充周次所属年份。"
                        )
                    iso_year = baseline_iso.year
                try:
                    return self._result(
                        date.fromisocalendar(iso_year, route.target_iso_week, 1),
                        "structured_iso_week",
                    )
                except ValueError as exc:
                    raise WeekResolutionError("ISO 周次无效，请重新说明目标周。") from exc
            if route.target_week is not None and re.search(
                r"(?:\b\d{4}-\d{1,2}-\d{1,2}\b|"
                r"(?:\d{4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号))",
                content,
            ):
                return self._result(
                    monday_for(route.target_week), "structured_explicit_date"
                )
            raise WeekResolutionError("无法可靠解析目标周，请补充 ISO 年份和周次。")

        normalized = content.lower()
        offset = None
        if any(token in normalized for token in ("再下一周", "下下周", "week after next")):
            offset = 14
        elif any(token in normalized for token in ("下一周", "下周", "next week")):
            offset = 7
        elif (any(token in normalized for token in ("上一周", "last week", "previous week"))
              or re.search(r"(?<!须)(?<!要)(?<!让)上周", normalized)):
            offset = -7
        if offset is not None:
            anchor = baseline or monday_for(today or date.today())
            return self._result(anchor + timedelta(days=offset), "relative_week")

        if trusted is not None:
            return self._result(trusted, "trusted_action")
        if referenced_week is not None:
            return self._result(referenced_week, "conversation_reference")
        if previous is not None:
            return self._result(previous, "conversation_reference")
        if workbench is not None:
            return self._result(workbench, "workbench")
        return self._result(monday_for(today or date.today()), "current_monday")

    @staticmethod
    def _result(week_start: date, source: str) -> ResolvedWeek:
        iso = week_start.isocalendar()
        return ResolvedWeek(week_start, iso.year, iso.week, source)
