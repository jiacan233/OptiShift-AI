from __future__ import annotations

import logging
from datetime import date, timedelta
from threading import Event, Thread
from typing import Any, NoReturn

from ..config import positive_seconds
from ..core import HistoryUnavailableError
from ..execution import ExecutionTimeout, ExecutionTrace, current_execution, execution_stage, traced
from ..models import ChangeType, Day, ForceRequest, Schedule, ScheduleChange
from ..repository import (
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationRepository,
    DraftPendingError,
    EmployeeRepository,
    ScheduleRepository,
    VersionConflictError,
)
from ..validator.authorization import compliance_fields
from .agent_context import ResolvedWeek, WeekResolutionError, WeekResolver
from .agent_router import (
    AgentClarification,
    AgentIntent,
    AgentRoute,
    AgentRouter,
    TrustedAgentAction,
    UnknownAgentEmployeeError,
)
from .agent_tools import AgentTools
from .llm_client import AgentLLMClient, AIUnavailableError
from .request_validator import validate_changes

_INFEASIBLE_RULE_NAMES = {
    "R01": "店长覆盖不足",
    "R02": "饮品制作覆盖不足",
    "R03": "收银覆盖不足",
    "R04": "最低在岗人数不足",
}
_INFEASIBLE_DAY_NAMES = {
    "Mon": "周一",
    "Tue": "周二",
    "Wed": "周三",
    "Thu": "周四",
    "Fri": "周五",
    "Sat": "周六",
    "Sun": "周日",
}
_INFEASIBLE_SHIFT_NAMES = {"morning": "早班", "evening": "晚班"}


class AgentTurnError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        turn_result: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.turn_result = turn_result
        self.details = details
        super().__init__(message)


class StaleSuggestionError(ValueError):
    pass


class AgentService:
    WRITE_INTENTS = {AgentIntent.GENERATE, AgentIntent.REPLAN}
    TURN_LEASE_TIMEOUT = timedelta(seconds=180)

    def __init__(
        self,
        conversations: ConversationRepository,
        employees: EmployeeRepository,
        schedules: ScheduleRepository,
        tools: AgentTools,
        *,
        router: AgentRouter | None = None,
        week_resolver: WeekResolver | None = None,
        llm: AgentLLMClient | None = None,
    ) -> None:
        self.TURN_LEASE_TIMEOUT = timedelta(seconds=max(
            positive_seconds("AGENT_TURN_LEASE_SECONDS", 180),
            positive_seconds("AGENT_TURN_TIMEOUT_SECONDS", 90) + 30,
        ))
        self.conversations = conversations
        self.employees = employees
        self.schedules = schedules
        self.tools = tools
        self.llm = llm or AgentLLMClient()
        self.router = router or AgentRouter(self.llm)
        self.week_resolver = week_resolver or WeekResolver()

    def create_conversation(self, browser_workspace_id: str) -> dict[str, Any]:
        return self.conversations.create_conversation(browser_workspace_id)

    def list_conversations(self, browser_workspace_id: str) -> list[dict[str, Any]]:
        return self.conversations.list_conversations(browser_workspace_id)

    def get_conversation(
        self, conversation_id: str, browser_workspace_id: str
    ) -> dict[str, Any]:
        conversation = self.conversations.get_conversation(
            conversation_id, browser_workspace_id
        )
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return {
            "conversation": conversation,
            "messages": self.conversations.list_messages(
                conversation_id, browser_workspace_id
            ),
            "tool_calls": self.conversations.list_tool_calls(
                conversation_id, browser_workspace_id
            ),
        }

    @staticmethod
    def _replay_turn(result: dict[str, Any]) -> dict[str, Any]:
        error = result.get("error")
        if isinstance(error, dict):
            code = str(error.get("code", "agent_error"))
            status = int(
                error.get("status_code")
                or (503 if code == "ai_unavailable" else 409)
            )
            raise AgentTurnError(
                status,
                code,
                str(error.get("message", code)),
                result,
                error.get("details") if isinstance(error.get("details"), dict) else None,
            )
        return result

    @staticmethod
    def _schedule_result_from_record(record: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(record.get("metadata") or {})
        schedule_status = str(record.get("status") or "draft")
        schedule = record.get("schedule")
        schedule_payload = (
            schedule.model_dump(mode="json")
            if isinstance(schedule, Schedule)
            else schedule
        )
        if isinstance(schedule_payload, dict):
            schedule_payload = {**schedule_payload, "status": schedule_status}
        return {
            "status": "confirmed" if schedule_status == "confirmed" else "feasible",
            "solver_status": metadata.get("solver_status", "feasible"),
            "schedule_id": record["schedule_id"],
            "version": record["version"],
            "schedule_status": schedule_status,
            "schedule": schedule_payload,
            "validation": record.get("validation") or {},
            "diff": metadata.get("diff") or {},
            "impact": metadata.get("impact") or {},
            "metrics": metadata.get("metrics") or {},
            "explanation": metadata.get("explanation") or {},
            **compliance_fields(record.get("validation") or {}, schedule_status),
        }

    @staticmethod
    def _current_after_draft(
        current: dict[str, Any], schedule_result: dict[str, Any], target_week: date
    ) -> dict[str, Any]:
        draft = {
            "schedule_id": schedule_result.get("schedule_id"),
            "version": schedule_result.get("version"),
            "status": "draft",
            "week_start": target_week.isoformat(),
            "schedule": schedule_result.get("schedule"),
            "validation": schedule_result.get("validation") or {},
            "metadata": {
                "diff": schedule_result.get("diff") or {},
                "impact": schedule_result.get("impact") or {},
                "metrics": schedule_result.get("metrics") or {},
                "explanation": schedule_result.get("explanation") or {},
            },
        }
        return {
            **current,
            "target_week": target_week.isoformat(),
            "draft": draft,
            "display": draft,
        }

    @staticmethod
    def _compose_infeasible_response(
        schedule_result: dict[str, Any], *, target_week: date | None = None
    ) -> str:
        """Build a deterministic, fact-based explanation for an infeasible solve."""

        if target_week is not None:
            iso = target_week.isocalendar()
            heading = f"当前约束下无法生成{iso.year}年第{iso.week}周排班。"
        else:
            heading = "当前约束下无法生成有效排班。"

        raw_conflicts = schedule_result.get("conflicts")
        conflicts = (
            [item for item in raw_conflicts if isinstance(item, dict)]
            if isinstance(raw_conflicts, list)
            else []
        )
        if conflicts:
            heading = f"{heading[:-1]}，共检测到 {len(conflicts)} 个主要冲突。"
            lines = [heading, "", "**主要冲突**", ""]
            for conflict in conflicts[:3]:
                rule_id = str(conflict.get("rule_id") or "硬约束")
                rule_name = _INFEASIBLE_RULE_NAMES.get(rule_id, rule_id)
                day = _INFEASIBLE_DAY_NAMES.get(
                    str(conflict.get("day") or ""), str(conflict.get("day") or "")
                )
                shift = _INFEASIBLE_SHIFT_NAMES.get(
                    str(conflict.get("shift") or ""), str(conflict.get("shift") or "")
                )
                slot = f"{day}{shift}" if day or shift else "相关班次"
                required = conflict.get("required")
                available = conflict.get("available")
                shortage = conflict.get("shortage")
                if required is not None or available is not None or shortage is not None:
                    details = (
                        f"需要 {required if required is not None else '?'} 人，"
                        f"当前可用 {available if available is not None else '?'} 人"
                    )
                    if shortage is not None:
                        details += f"，缺少 {shortage} 人"
                else:
                    details = str(conflict.get("message") or "该班次无法满足此硬约束")
                lines.append(f"- {slot}：{rule_id} {rule_name}，{details}")
            if len(conflicts) > 3:
                lines.append(f"- 其余 {len(conflicts) - 3} 个冲突见下方详细诊断。")
            return "\n".join(lines)

        lines = [
            heading,
            "",
            "未发现单一的 R01-R04 人员覆盖缺口，当前不可行来自其他保留硬约束，或多条硬约束之间的组合冲突。",
        ]
        diagnosis = schedule_result.get("diagnosis")
        if isinstance(diagnosis, dict) and diagnosis.get("summary"):
            lines.extend(["", f"详细诊断：{diagnosis['summary']}"])
        else:
            lines.extend(["", "详细诊断见下方。"])
        return "\n".join(lines)

    @staticmethod
    def _compact_infeasible_result(result: dict[str, Any]) -> dict[str, Any]:
        """Keep enough solver facts for a follow-up without copying a large diagnosis."""

        diagnosis = result.get("diagnosis")
        compact_diagnosis = None
        if isinstance(diagnosis, dict):
            compact_diagnosis = {
                key: diagnosis[key]
                for key in ("summary", "diagnostic_status")
                if key in diagnosis
            }
        return {
            "status": "infeasible",
            "conflicts": [item for item in (result.get("conflicts") or []) if isinstance(item, dict)][:5],
            "blocking_candidates": [
                item for item in (result.get("blocking_candidates") or []) if isinstance(item, dict)
            ][:5],
            "diagnosis": compact_diagnosis,
            "message": result.get("message") or "No valid schedule exists.",
            "generated_valid_schedule": False,
            "preview_schedule": result.get("preview_schedule"),
            "coverage_gaps": [
                item for item in (result.get("coverage_gaps") or []) if isinstance(item, dict)
            ][:12],
            "strict_feasible": False,
            "suggestions": [
                item for item in (result.get("suggestions") or []) if isinstance(item, dict)
            ][:4],
        }

    def _finalize_clarification_turn(
        self,
        *,
        conversation_id: str,
        browser_workspace_id: str,
        client_message_id: str,
        owner_token: str,
        user_message: dict[str, Any],
        route: AgentRoute,
        target: ResolvedWeek,
        trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist a pending question without reading or mutating schedules."""
        question = route.clarification.question or "请补充完成这次操作所需的信息。"
        metadata = {
            "target_week": target.week_start.isoformat(),
            "context": {**target.as_dict()},
            "clarification": {"required": True, "question": question},
            "tool_call_ids": [item["tool_call_id"] for item in trace],
        }
        return self.conversations.finalize_turn(
            conversation_id,
            browser_workspace_id,
            client_message_id=client_message_id,
            owner_token=owner_token,
            content=question,
            intent=AgentIntent.CLARIFICATION.value,
            mutation_requested=False,
            target_week=target.week_start,
            referenced_schedule_id=None,
            referenced_version=None,
            metadata=metadata,
            conversation_summary=f"待澄清：{question}",
            result_fields={
                "intent": AgentIntent.CLARIFICATION.value,
                "mutation_requested": False,
                "context": {**target.as_dict()},
                "tool_calls": trace,
                "schedule_result": None,
            },
        )

    def _close_running_tool_calls(
        self,
        *,
        conversation_id: str,
        browser_workspace_id: str,
        trace: list[dict[str, Any]],
        owner_token: str,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for call in trace:
            if call.get("status") == "running":
                call = self.conversations.finish_tool_call(
                    call["tool_call_id"],
                    conversation_id,
                    browser_workspace_id,
                    output_json={
                        "error": "turn lease expired",
                        "type": "TurnInterrupted",
                    },
                    status="failed",
                    owner_token=owner_token,
                )
            normalized.append(call)
        return normalized

    def _recover_incomplete_turn(
        self,
        *,
        conversation_id: str,
        browser_workspace_id: str,
        client_message_id: str,
        user_message: dict[str, Any],
        owner_token: str,
    ) -> dict[str, Any] | None:
        """Finalize a turn whose deterministic write committed before its reply."""

        trace = self.conversations.list_tool_calls(
            conversation_id,
            browser_workspace_id,
            message_id=user_message["message_id"],
        )
        write_call = next(
            (
                item
                for item in reversed(trace)
                if item.get("tool_name") in {"generate_schedule", "replan_schedule", "force_generate_schedule"}
            ),
            None,
        )
        if write_call is None:
            return None
        inputs = write_call.get("input") or {}
        raw_week = inputs.get("target_week") or user_message.get("target_week")
        if not isinstance(raw_week, str):
            return None
        try:
            target_week = date.fromisoformat(raw_week)
        except ValueError:
            return None

        source_record = self.schedules.find_agent_schedule_for_turn(
            target_week,
            conversation_id=conversation_id,
            client_message_id=client_message_id,
            user_message_id=user_message["message_id"],
        )
        output = write_call.get("output")
        schedule_result = output if isinstance(output, dict) else None
        if schedule_result is None or write_call.get("status") != "completed":
            metadata = dict((source_record or {}).get("metadata") or {})
            if (
                source_record is None
                or metadata.get("agent_conversation_id") != conversation_id
                or metadata.get("agent_client_message_id") != client_message_id
                or metadata.get("agent_user_message_id") != user_message["message_id"]
            ):
                return None
            schedule_result = self._schedule_result_from_record(source_record)
            finished = self.conversations.finish_tool_call(
                write_call["tool_call_id"],
                conversation_id,
                browser_workspace_id,
                output_json=schedule_result,
                status="completed",
                owner_token=owner_token,
            )
            trace = [
                finished if item["tool_call_id"] == finished["tool_call_id"] else item
                for item in trace
            ]

        trace = self._close_running_tool_calls(
            conversation_id=conversation_id,
            browser_workspace_id=browser_workspace_id,
            trace=trace,
            owner_token=owner_token,
        )

        try:
            current = self.tools.get_current_schedule(target_week=target_week)
        except Exception:
            current = self._current_after_draft({}, schedule_result, target_week)
        display = current.get("display") or {}
        confirmed = current.get("confirmed") or {}
        iso = target_week.isocalendar()
        context_payload = {
            "target_week": target_week.isoformat(),
            "iso_year": iso.year,
            "iso_week": iso.week,
            "resolution_source": "recovered_idempotent_turn",
            "display_schedule_id": display.get("schedule_id"),
            "display_schedule_version": display.get("version"),
            "confirmed_schedule_id": confirmed.get("schedule_id"),
            "confirmed_schedule_version": confirmed.get("version"),
        }
        intent = (
            AgentIntent.GENERATE
            if write_call["tool_name"] in {"generate_schedule", "force_generate_schedule"}
            else AgentIntent.REPLAN
        )
        schedule_created = schedule_result.get("status") in {"feasible", "confirmed"}
        recovered_schedule_status = (
            str(
                (source_record or {}).get("status")
                or schedule_result.get("schedule_status")
                or "draft"
            )
            if schedule_created
            else "not_created"
        )
        if schedule_created:
            if recovered_schedule_status == "confirmed":
                response_content = (
                    f"原请求已生成{iso.year}年第{iso.week}周排班草稿 "
                    f"v{schedule_result['version']}；该版本目前已确认。"
                )
            elif recovered_schedule_status == "cancelled":
                response_content = (
                    f"原请求已生成{iso.year}年第{iso.week}周排班草稿 "
                    f"v{schedule_result['version']}；该草稿目前已取消。"
                )
            else:
                response_content = (
                    f"已生成{iso.year}年第{iso.week}周排班草稿 "
                    f"v{schedule_result['version']}。请在工作台检查后手动确认。"
                )
        else:
            response_content = self._compose_infeasible_response(
                schedule_result, target_week=target_week
            ) if schedule_result.get("status") == "infeasible" else "恢复求解结果未创建草稿，请重新发送请求。"
        conversation = self.conversations.get_conversation(
            conversation_id, browser_workspace_id
        )
        recovery_summary_items = [
            f"用户近期目标：{str(user_message.get('content') or '')[:180]}",
            f"最近目标周：{target_week.isoformat()}",
            f"最近意图：{intent.value}",
        ]
        if schedule_created:
            recovery_summary_items.append(
                "恢复排班："
                f"{schedule_result.get('schedule_id')}@{schedule_result.get('version')}，"
                f"当前状态={recovered_schedule_status}"
            )
        else:
            recovery_summary_items.append(
                f"恢复求解结果：{schedule_result.get('status')}，未创建草稿"
            )
        previous_summary = (conversation or {}).get("summary")
        if previous_summary:
            recovery_summary_items.insert(
                0, f"既有摘要：{str(previous_summary)[-600:]}"
            )
        recovery_summary = "；".join(recovery_summary_items)[-1400:]
        recovery_metadata = {
            "target_week": target_week.isoformat(),
            "context": context_payload,
            "generated_draft_id": schedule_result.get("schedule_id"),
            "generated_draft_version": schedule_result.get("version"),
            "recovered_schedule_status": recovered_schedule_status,
            "tool_call_ids": [item["tool_call_id"] for item in trace],
            "recovered": True,
        }
        if schedule_result.get("status") == "infeasible":
            recovery_metadata["infeasible_result"] = dict(schedule_result)
        return self.conversations.finalize_turn(
            conversation_id,
            browser_workspace_id,
            client_message_id=client_message_id,
            owner_token=owner_token,
            content=response_content,
            intent=intent.value,
            mutation_requested=True,
            target_week=target_week,
            referenced_schedule_id=(
                schedule_result.get("schedule_id") or display.get("schedule_id")
            ),
            referenced_version=(
                schedule_result.get("version") or display.get("version")
            ),
            metadata=recovery_metadata,
            conversation_summary=recovery_summary,
            result_fields={
                "intent": intent.value,
                "mutation_requested": True,
                "context": context_payload,
                "tool_calls": trace,
                "schedule_result": schedule_result,
            },
        )

    def _finalize_stale_turn(
        self,
        *,
        conversation_id: str,
        browser_workspace_id: str,
        user_message: dict[str, Any],
        owner_token: str,
    ) -> dict[str, Any]:
        trace = self.conversations.list_tool_calls(
            conversation_id,
            browser_workspace_id,
            message_id=user_message["message_id"],
        )
        normalized_trace = self._close_running_tool_calls(
            conversation_id=conversation_id,
            browser_workspace_id=browser_workspace_id,
            trace=trace,
            owner_token=owner_token,
        )
        trace = normalized_trace
        raw_week = user_message.get("target_week")
        target_week = None
        if isinstance(raw_week, str):
            try:
                target_week = date.fromisoformat(raw_week)
            except ValueError:
                target_week = None
        message = "先前的请求在服务中断后未完成，请重新发送。"
        return self.conversations.finalize_turn(
            conversation_id,
            browser_workspace_id,
            client_message_id=user_message["client_message_id"],
            owner_token=owner_token,
            content=message,
            intent=user_message.get("intent"),
            mutation_requested=False,
            target_week=target_week,
            metadata={
                "error": {"code": "turn_interrupted", "status_code": 409},
                "tool_call_ids": [item["tool_call_id"] for item in trace],
            },
            result_fields={
                "intent": user_message.get("intent"),
                "mutation_requested": False,
                "context": None,
                "tool_calls": trace,
                "schedule_result": None,
                "error": {
                    "code": "turn_interrupted",
                    "message": message,
                    "status_code": 409,
                },
            },
        )

    @staticmethod
    def _public_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed_metadata = {
            "suggestions",
            "referenced_suggestion",
            "target_week",
            "context",
            "generated_draft_id",
            "generated_draft_version",
            "current_week_start",
            "trusted_action",
            "error",
            "infeasible_result",
            "scenario_preview",
        }
        result = []
        for item in messages[-12:]:
            metadata = item.get("metadata") or item.get("metadata_json") or {}
            public_metadata = {
                key: value
                for key, value in metadata.items()
                if key in allowed_metadata
            }
            infeasible_result = public_metadata.get("infeasible_result")
            if isinstance(infeasible_result, dict):
                public_metadata["infeasible_result"] = AgentService._compact_infeasible_result(
                    infeasible_result
                )
            result.append(
                {
                    "role": item.get("role"),
                    "content": item.get("content"),
                    "intent": item.get("intent"),
                    "target_week": item.get("target_week"),
                    "metadata": public_metadata,
                }
            )
        return result

    @staticmethod
    def _restore_request_snapshot(
        user_message: dict[str, Any],
    ) -> tuple[str, date | None, TrustedAgentAction | None]:
        """Restore the immutable request attached to an idempotent user message."""

        metadata = dict(user_message.get("metadata") or {})
        raw_week = metadata.get("current_week_start")
        restored_week = date.fromisoformat(raw_week) if isinstance(raw_week, str) else None
        raw_action = metadata.get("trusted_action")
        restored_action = (
            TrustedAgentAction.model_validate(raw_action)
            if isinstance(raw_action, dict)
            else None
        )
        return str(user_message["content"]), restored_week, restored_action

    @staticmethod
    def _suggestions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in reversed(messages):
            metadata = message.get("metadata") or {}
            suggestions = metadata.get("suggestions")
            if isinstance(suggestions, list):
                result.extend(item for item in suggestions if isinstance(item, dict))
        return result

    @classmethod
    def _resolve_suggestion(
        cls, route: AgentRoute, messages: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if route.reference.type == "none":
            return None
        suggestion_id = route.reference.suggestion_id
        if route.reference.type == "previous_message" and suggestion_id is None:
            for message in reversed(messages):
                metadata = message.get("metadata") or {}
                referenced = metadata.get("referenced_suggestion")
                if isinstance(referenced, dict):
                    return referenced
                suggestions = metadata.get("suggestions")
                if isinstance(suggestions, list) and suggestions:
                    candidate = suggestions[-1]
                    if isinstance(candidate, dict):
                        return candidate
            return None
        for suggestion in cls._suggestions(messages):
            if suggestion.get("id") == suggestion_id:
                return suggestion
        return None

    def _run_tool(
        self,
        *,
        conversation_id: str,
        browser_workspace_id: str,
        message_id: str,
        owner_token: str,
        tool_name: str,
        inputs: dict[str, Any],
        trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        persisted_inputs = {
            key: (
                [item.model_dump(mode="json") for item in value]
                if isinstance(value, list)
                and value
                and isinstance(value[0], ScheduleChange)
                else value.model_dump(mode="json")
                if isinstance(value, ForceRequest)
                else value.isoformat()
                if isinstance(value, date)
                else value
            )
            for key, value in inputs.items()
            if not key.startswith("_")
        }
        call = self.conversations.add_tool_call(
            conversation_id,
            browser_workspace_id,
            message_id=message_id,
            tool_name=tool_name,
            input_json=persisted_inputs,
            owner_token=owner_token,
        )
        try:
            with execution_stage("tool"):
                output = self.tools.run(tool_name, **inputs)
        except Exception as exc:
            finished = self.conversations.finish_tool_call(
                call["tool_call_id"],
                conversation_id,
                browser_workspace_id,
                output_json={"error": "排班操作失败", "type": type(exc).__name__},
                status="failed",
                owner_token=owner_token,
            )
            trace.append(finished)
            raise
        finished = self.conversations.finish_tool_call(
            call["tool_call_id"],
            conversation_id,
            browser_workspace_id,
            output_json=output,
            status="completed",
            owner_token=owner_token,
        )
        trace.append(finished)
        return output

    def _complete_failure(
        self,
        *,
        conversation_id: str,
        browser_workspace_id: str,
        client_message_id: str,
        owner_token: str,
        user_message: dict[str, Any],
        code: str,
        message: str,
        status_code: int,
        intent: str | None = None,
        target_week: date | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> NoReturn:
        result = self.conversations.finalize_turn(
            conversation_id,
            browser_workspace_id,
            client_message_id=client_message_id,
            owner_token=owner_token,
            content=message,
            intent=intent,
            mutation_requested=False,
            target_week=target_week,
            metadata={
                "error": {
                    "code": code,
                    "status_code": status_code,
                    "details": error_details,
                },
                "tool_call_ids": [
                    item["tool_call_id"] for item in (tool_calls or [])
                ],
            },
            result_fields={
                "intent": intent,
                "mutation_requested": False,
                "context": None,
                "tool_calls": tool_calls or [],
                "schedule_result": None,
                "error": {
                    "code": code,
                    "message": message,
                    "status_code": status_code,
                    "details": error_details,
                },
            },
        )
        raise AgentTurnError(status_code, code, message, result, error_details)

    @traced("resolve_context")
    def _resolve_week(
        self,
        *,
        content: str,
        route: AgentRoute,
        current_week_start: date | None,
        messages: list[dict[str, Any]],
        suggestion: dict[str, Any] | None,
        trusted_week: date | None = None,
    ) -> ResolvedWeek:
        referenced_week = None
        if suggestion and suggestion.get("target_week"):
            referenced_week = date.fromisoformat(str(suggestion["target_week"]))
        return self.week_resolver.resolve(
            content=content,
            route=route,
            current_week_start=current_week_start,
            recent_messages=messages,
            referenced_week=referenced_week,
            trusted_week=trusted_week,
        )

    @staticmethod
    def _make_suggestions(
        target: ResolvedWeek, analysis: dict[str, Any], current: dict[str, Any]
    ) -> list[dict[str, Any]]:
        display = current.get("display") or {}
        confirmed = current.get("confirmed") or {}
        basis = (
            display
            if display.get("schedule_id") == analysis.get("schedule_id")
            else confirmed or display
        )
        schedule_id = basis.get("schedule_id")
        version = basis.get("version")
        workload = analysis.get("workload") or {}
        metrics = analysis.get("metrics") or {}
        if schedule_id is None:
            return [
                {
                    "id": "suggestion_1",
                    "suggestion_id": "suggestion_1",
                    "title": "先生成本周排班草稿",
                    "description": "当前周还没有排班，可以先让确定性 Solver 生成一版草稿。",
                    "proposed_changes": [],
                    "target_week": target.week_start.isoformat(),
                    "based_on_schedule_id": None,
                    "based_on_version": None,
                    "action": "generate",
                }
            ]
        busiest = max(workload, key=workload.get) if workload else None
        display_schedule = (current.get("display") or {}).get("schedule") or {}
        busiest_assignment = next(
            (
                item
                for item in display_schedule.get("assignments", [])
                if item.get("employee_id") == busiest
            ),
            None,
        )
        balance_changes = (
            [
                {
                    "employee_id": busiest,
                    "type": ChangeType.UNASSIGN.value,
                    "day": busiest_assignment["day"],
                    "shift": busiest_assignment["shift"],
                }
            ]
            if busiest and busiest_assignment
            else []
        )
        balance_detail = (
            f"可以尝试释放 {busiest} 的 {busiest_assignment['day']} "
            f"{busiest_assignment['shift']} 班次"
            if balance_changes
            else "可以让 Solver 以最小改动目标重新检查分配"
        )
        return [
            {
                "id": "suggestion_1",
                "suggestion_id": "suggestion_1",
                "title": "复核员工班次偏好",
                "description": (
                    f"当前偏好满足率约为 {float(metrics.get('preference_rate', 0)):.0%}，"
                    "可在保持硬规则成立的前提下重新优化。"
                ),
                "proposed_changes": [],
                "target_week": target.week_start.isoformat(),
                "based_on_schedule_id": schedule_id,
                "based_on_version": version,
                "action": "replan",
            },
            {
                "id": "suggestion_2",
                "suggestion_id": "suggestion_2",
                "title": "复核工作量均衡",
                "description": (
                    f"当前工作量差值为 {metrics.get('workload_gap', 0)}"
                    + (f"，{busiest} 的班次最多。" if busiest else "。")
                    + f" {balance_detail}，再由 Solver 验证并由人工确认。"
                ),
                "proposed_changes": balance_changes,
                "target_week": target.week_start.isoformat(),
                "based_on_schedule_id": schedule_id,
                "based_on_version": version,
                "action": "replan",
            },
        ]

    @traced("response_compose")
    def _compose_read_response(
        self,
        *,
        route: AgentRoute,
        content: str,
        target: ResolvedWeek,
        current: dict[str, Any],
        tool_output: dict[str, Any] | None,
        suggestion: dict[str, Any] | None,
    ) -> str:
        normalized = content.strip().lower().strip("。.!！ ")
        if normalized in {"确认", "应用", "就这样", "可以", "确认这个版本"}:
            return "聊天不能直接确认排班。请在工作台检查草稿后点击“确认变更”。"
        if route.intent is AgentIntent.CLARIFICATION:
            return route.clarification.question or "请补充完成这次操作所需的信息。"
        if route.intent is AgentIntent.OUT_OF_SCOPE:
            return "我目前只能协助排班分析、规则解释、校验以及创建排班草稿。"
        if route.intent is AgentIntent.VALIDATE:
            validation = (tool_output or {}).get("validation")
            if validation is None:
                return f"{target.iso_year}年第{target.iso_week}周还没有可校验的排班。"
            if validation.get("passed"):
                return f"{target.iso_year}年第{target.iso_week}周已通过全部硬规则校验。"
            if validation.get("compliance_status") == "authorized_violations":
                return f"当前排班存在 {len(validation.get('authorized_violations', []))} 项已授权规则例外，并非全部合规；可在工作台查看每条例外并确认草稿。"
            failed = [
                item.get("rule_id")
                for item in validation.get("checks", [])
                if not item.get("passed")
            ]
            return "当前排班未通过校验，涉及规则：" + "、".join(filter(None, failed))
        if route.intent is AgentIntent.EXPLAIN and suggestion is not None:
            return (
                f"“{suggestion.get('title', '该建议')}”基于排班 v"
                f"{suggestion.get('based_on_version')} 的真实指标提出。"
                f"{suggestion.get('description', '')} 只有重新求解并校验后，才能确认具体改动可行。"
            )
        display_validation = ((tool_output or {}).get("display") or {}).get("validation") or {}
        if display_validation.get("compliance_status") == "authorized_violations":
            facts = [
                f"{item['rule_id']} {item.get('day')} {item.get('shift')} {item.get('employee_id') or ''}：要求 {item.get('expected')}，实际 {item.get('actual')}，已授权"
                for item in display_validation.get("authorized_violations", [])
            ]
            return "当前排班保留以下真实规则例外：" + "；".join(facts) + "。其余规则仍由独立校验器检查。"
        if route.intent is AgentIntent.EXPLAIN and not self.llm.enabled:
            employee_id = route.employees[0] if route.employees else None
            display = (tool_output or {}).get("display") or {}
            schedule = display.get("schedule") or {}
            assignments = [
                item
                for item in schedule.get("assignments", [])
                if employee_id is not None and item.get("employee_id") == employee_id
            ]
            employee = next(
                (
                    item
                    for item in (tool_output or {}).get("employees", [])
                    if item.get("id") == employee_id
                ),
                None,
            )
            if employee_id is None or employee is None:
                return "请说明要解释的员工编号和具体班次。"
            return (
                f"{employee_id} 本周共有 {len(assignments)} 个班次。当前安排与其技能、"
                "可工作日期、偏好以及覆盖规则一致；未做反事实验证前，不能断言该员工是唯一人选。"
            )
        if route.intent is AgentIntent.ASK and not self.llm.enabled:
            return (
                "OptiShift 使用员工主数据、H01/R01-R09 硬规则和 S01-S03 软目标构建排班，"
                "由 CP-SAT Solver 生成草稿，再经过独立 Validator 校验。正式生效仍需人工点击确认。"
            )
        if route.intent is AgentIntent.ADVICE and not self.llm.enabled:
            impact = (tool_output or {}).get("impact") or {}
            if route.changes:
                affected_count = int(impact.get("affected_count", 0))
                if affected_count:
                    return (
                        f"这项变更会直接影响{target.iso_year}年第{target.iso_week}周的 "
                        f"{affected_count} 个现有班次，需要重新排班并再次校验规则；"
                        "当前只做了影响分析，没有创建草稿。"
                    )
                return "当前排班没有找到会被这项变更直接移除的班次；本次只读分析没有创建草稿。"
            return f"我已根据{target.iso_year}年第{target.iso_week}周的真实排班、员工和规则生成建议。"
        if self.llm.enabled:
            return self.llm.complete_text(
                system=(
                    "Answer as a concise scheduling assistant using only the supplied facts. "
                    "Do not claim an assignment is uniquely necessary without "
                    "counterfactual evidence. "
                    "Do not say a schedule was confirmed."
                ),
                user={
                    "question": content,
                    "intent": route.intent.value,
                    "target_week": target.week_start.isoformat(),
                    "current_schedule": current,
                    "tool_result": tool_output,
                    "requested_changes": [
                        item.model_dump(mode="json") for item in route.changes
                    ],
                },
            )
        return "我已读取当前排班上下文。"

    def _validate_suggestion_for_replan(
        self,
        *,
        suggestion: dict[str, Any],
        target: ResolvedWeek,
        current: dict[str, Any],
    ) -> tuple[list[ScheduleChange], bool]:
        if suggestion.get("target_week") != target.week_start.isoformat():
            raise WeekResolutionError("该建议对应另一周，请确认要操作的目标周。")
        confirmed = current.get("confirmed")
        if confirmed is None:
            raise ValueError("该建议所依据的正式排班已不存在。")
        changes = [
            ScheduleChange.model_validate(item)
            for item in suggestion.get("proposed_changes", [])
        ]
        employee_list = self.employees.list()
        validate_changes(changes, employee_list)
        based_on_id = suggestion.get("based_on_schedule_id")
        based_on_version = suggestion.get("based_on_version")
        rebased = (
            confirmed.get("schedule_id") != based_on_id
            or confirmed.get("version") != based_on_version
        )
        if rebased and changes:
            schedule = Schedule.model_validate(confirmed["schedule"])
            assignment_keys = {
                (item.employee_id, item.day) for item in schedule.assignments
            }
            for change in changes:
                if change.type in {ChangeType.LEAVE, ChangeType.UNAVAILABLE} and (
                    change.employee_id,
                    change.day,
                ) not in assignment_keys:
                    raise StaleSuggestionError(
                        "该建议对应的员工班次已经变化，建议已不再适用。"
                    )
                if change.type is ChangeType.UNASSIGN and not any(
                    item.employee_id == change.employee_id
                    and item.day == change.day
                    and item.shift == change.shift
                    for item in schedule.assignments
                ):
                    raise StaleSuggestionError(
                        "该建议引用的具体班次已经变化，建议已不再适用。"
                    )
        return changes, rebased

    def send_message(self, *, event_sink=None, **request) -> dict[str, Any]:
        execution = ExecutionTrace(request["conversation_id"], request["client_message_id"], event_sink)
        token = current_execution.set(execution)
        stop = Event()

        def renew():
            while not stop.wait(min(15, self.TURN_LEASE_TIMEOUT.total_seconds() / 3)):
                if execution.owner is not None:
                    user, owner = execution.owner
                    try:
                        self.conversations.renew_turn(
                            request["conversation_id"], request["browser_workspace_id"],
                            message_id=user["message_id"], owner_token=owner,
                        )
                    except Exception:
                        # Commit still checks the owner under the database lock.
                        logging.getLogger("optishift.execution").warning("turn_renewal_failed")
                        return

        renewal = Thread(target=renew, name="agent-lease", daemon=True)
        renewal.start()
        execution.emit("turn_started", "completed")
        try:
            try:
                result = self._send_message(**request)
            except ExecutionTimeout as exc:
                if execution.owner is None:
                    raise AgentTurnError(504, "agent_turn_timeout", str(exc), details={
                        "stage": exc.stage, "error_type": exc.error_type, "latency_ms": exc.latency_ms,
                    }) from exc
                user, owner = execution.owner
                recovery: dict[str, Any] = dict(
                    conversation_id=request["conversation_id"],
                    browser_workspace_id=request["browser_workspace_id"],
                    client_message_id=request["client_message_id"],
                    user_message=user, owner_token=owner,
                )
                recovered = self._recover_incomplete_turn(**recovery)
                if recovered is not None:
                    result = self._replay_turn(recovered)
                else:
                    self._complete_failure(**recovery, code="agent_turn_timeout", message=str(exc),
                                           status_code=504, error_details={
                                               "error_type": exc.error_type,
                                               "stage": exc.stage, "latency_ms": exc.latency_ms,
                                           })
            execution.finish()
            assert execution.terminal_event is not None
            execution.publish(execution.terminal_event)
            return result
        except Exception:
            execution.finish(failed=True)
            assert execution.terminal_event is not None
            execution.publish(execution.terminal_event)
            raise
        finally:
            stop.set()
            renewal.join(timeout=1)
            current_execution.reset(token)

    def _send_message(
        self,
        *,
        conversation_id: str,
        browser_workspace_id: str,
        client_message_id: str,
        content: str,
        current_week_start: date | None = None,
        trusted_action: TrustedAgentAction | None = None,
    ) -> dict[str, Any]:
        existing = self.conversations.get_idempotent_turn_result(
            conversation_id, browser_workspace_id, client_message_id
        )
        if existing is not None:
            return self._replay_turn(existing)

        prior_trace: list[dict[str, Any]] = []
        message_metadata = {
            "current_week_start": (
                current_week_start.isoformat() if current_week_start else None
            ),
            "trusted_action": (
                trusted_action.model_dump(mode="json") if trusted_action else None
            ),
        }
        try:
            user_message, created, owner_token = self.conversations.add_user_message(
                conversation_id,
                browser_workspace_id,
                client_message_id=client_message_id,
                content=content,
                metadata=message_metadata,
            )
        except ConversationBusyError:
            stale = self.conversations.claim_stale_active_turn(
                conversation_id,
                browser_workspace_id,
                stale_after=self.TURN_LEASE_TIMEOUT,
            )
            if stale is None:
                raise
            stale_user, stale_owner = stale
            recovered = self._recover_incomplete_turn(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=stale_user["client_message_id"],
                user_message=stale_user,
                owner_token=stale_owner,
            )
            if recovered is None:
                self._finalize_stale_turn(
                    conversation_id=conversation_id,
                    browser_workspace_id=browser_workspace_id,
                    user_message=stale_user,
                    owner_token=stale_owner,
                )
            user_message, created, owner_token = self.conversations.add_user_message(
                conversation_id,
                browser_workspace_id,
                client_message_id=client_message_id,
                content=content,
                metadata=message_metadata,
            )
        if not created:
            completed = self.conversations.get_idempotent_turn_result(
                conversation_id, browser_workspace_id, client_message_id
            )
            if completed is not None:
                return self._replay_turn(completed)
            owner_token = self.conversations.reclaim_turn(
                conversation_id,
                browser_workspace_id,
                client_message_id=client_message_id,
                stale_after=self.TURN_LEASE_TIMEOUT,
            )
            if owner_token is None:
                raise AgentTurnError(
                    409,
                    "message_processing",
                    "This message is already being processed.",
                )
            recovered = self._recover_incomplete_turn(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                user_message=user_message,
                owner_token=owner_token,
            )
            if recovered is not None:
                return self._replay_turn(recovered)
            prior_trace = self.conversations.list_tool_calls(
                conversation_id,
                browser_workspace_id,
                message_id=user_message["message_id"],
            )
            prior_trace = self._close_running_tool_calls(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                trace=prior_trace,
                owner_token=owner_token,
            )
            content, current_week_start, trusted_action = self._restore_request_snapshot(
                user_message
            )
        if owner_token is None:
            raise AgentTurnError(409, "message_processing", "Turn lease is unavailable.")

        execution = current_execution.get()
        if execution:
            execution.owner = (user_message, owner_token)
        messages = self.conversations.list_messages(
            conversation_id, browser_workspace_id
        )
        prior_messages = [
            item for item in messages if item["message_id"] != user_message["message_id"]
        ]
        employees = self.employees.list()
        conversation = self.conversations.get_conversation(
            conversation_id, browser_workspace_id
        )
        try:
            route = self.router.route(
                content,
                employees=employees,
                recent_messages=self._public_messages(prior_messages),
                conversation_summary=(conversation or {}).get("summary"),
                trusted_action=trusted_action,
            )
        except UnknownAgentEmployeeError as exc:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="entity_not_found",
                message=f"员工主数据中不存在：{', '.join(exc.employee_ids)}。",
                status_code=404,
            )
            raise AssertionError("unreachable")
        except AIUnavailableError as exc:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="ai_unavailable",
                message=exc.safe_message,
                status_code=503,
                error_details=exc.public_details,
            )
            raise AssertionError("unreachable")

        self.conversations.renew_turn(
            conversation_id,
            browser_workspace_id,
            message_id=user_message["message_id"],
            owner_token=owner_token,
        )

        if route.clarification.required:
            route = route.model_copy(
                update={
                    "intent": AgentIntent.CLARIFICATION,
                    "mutation_requested": False,
                    "changes": [],
                }
            )

        suggestion = self._resolve_suggestion(route, prior_messages)
        if route.reference.type != "none" and suggestion is None:
            route = route.model_copy(
                update={
                    "intent": AgentIntent.CLARIFICATION,
                    "mutation_requested": False,
                    "clarification": AgentClarification(
                        required=True,
                        question="我找不到你指的那条建议，请说明建议编号。",
                    ),
                }
            )
        elif suggestion is not None and route.mutation_requested:
            scenario_patch = suggestion.get("scenario_patch")
            if isinstance(scenario_patch, dict):
                try:
                    patch_days = [Day(str(item)) for item in scenario_patch.get("days", [])]
                    patch_type = ChangeType(str(scenario_patch.get("change_type", "leave")))
                    scenario_changes = [
                        ScheduleChange(
                            employee_id=str(scenario_patch["employee_id"]),
                            type=patch_type,
                            day=day,
                        )
                        for day in patch_days
                    ]
                except (KeyError, ValueError) as exc:
                    self._complete_failure(
                        conversation_id=conversation_id,
                        browser_workspace_id=browser_workspace_id,
                        client_message_id=client_message_id,
                        owner_token=owner_token,
                        user_message=user_message,
                        code="scenario_patch_invalid",
                        message="该建议的临时条件已失效，无法应用。",
                        status_code=422,
                        intent=route.intent.value,
                    )
                    raise AssertionError("unreachable") from exc
                route = route.model_copy(
                    update={
                        "intent": AgentIntent.WHAT_IF,
                        "changes": scenario_changes,
                        "employees": [str(scenario_patch["employee_id"])],
                        "mutation_requested": True,
                    }
                )
                suggestion = None
            else:
                suggestion_action = suggestion.get("action", "replan")
                if suggestion_action == "generate":
                    if (
                        suggestion.get("based_on_schedule_id") is not None
                        or suggestion.get("based_on_version") is not None
                        or suggestion.get("proposed_changes")
                    ):
                        self._complete_failure(
                            conversation_id=conversation_id,
                            browser_workspace_id=browser_workspace_id,
                            client_message_id=client_message_id,
                            owner_token=owner_token,
                            user_message=user_message,
                            code="invalid_agent_action",
                            message="生成建议包含无效的排班版本引用。",
                            status_code=422,
                            intent=route.intent.value,
                        )
                        raise AssertionError("unreachable")
                    route = route.model_copy(
                        update={
                            "intent": AgentIntent.GENERATE,
                            "changes": [],
                            "employees": [],
                        }
                    )
                elif suggestion_action == "replan":
                    route = route.model_copy(update={"intent": AgentIntent.REPLAN})
                else:
                    self._complete_failure(
                        conversation_id=conversation_id,
                        browser_workspace_id=browser_workspace_id,
                        client_message_id=client_message_id,
                        owner_token=owner_token,
                        user_message=user_message,
                        code="invalid_agent_action",
                        message="建议操作类型无效。",
                        status_code=422,
                        intent=route.intent.value,
                    )
                    raise AssertionError("unreachable")
        try:
            target = self._resolve_week(
                content=content,
                route=route,
                current_week_start=current_week_start,
                messages=prior_messages,
                suggestion=suggestion,
                trusted_week=(trusted_action.target_week if trusted_action else None),
            )
        except WeekResolutionError as exc:
            route = AgentRoute(
                intent=AgentIntent.CLARIFICATION,
                mutation_requested=False,
                clarification={"required": True, "question": exc.question},
            )
            target = self.week_resolver.resolve(
                content="",
                route=route,
                current_week_start=current_week_start,
                recent_messages=prior_messages,
            )

        annotate = getattr(self.conversations, "annotate_user_message", None)
        if annotate is not None:
            annotate(
                conversation_id,
                browser_workspace_id,
                user_message["message_id"],
                intent=route.intent.value,
                mutation_requested=route.mutation_requested,
                target_week=target.week_start,
                referenced_schedule_id=(
                    suggestion.get("based_on_schedule_id") if suggestion else None
                ),
                referenced_version=(
                    suggestion.get("based_on_version") if suggestion else None
                ),
                owner_token=owner_token,
            )
            user_message = self.conversations.find_user_by_client_message_id(
                conversation_id, browser_workspace_id, client_message_id
            ) or user_message

        trace: list[dict[str, Any]] = prior_trace
        if route.clarification.required:
            return self._finalize_clarification_turn(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                route=route,
                target=target,
                trace=trace,
            )
        try:
            current = self._run_tool(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                message_id=user_message["message_id"],
                owner_token=owner_token,
                tool_name="get_current_schedule",
                inputs={"target_week": target.week_start},
                trace=trace,
            )
            schedule_result = None
            tool_output: dict[str, Any] | None = current
            metadata: dict[str, Any] = {}
            save_scenario_requested = any(
                token in content.lower()
                for token in ("保存当前方案", "采用当前方案", "生成正式草稿")
            )
            scenario_requested = (
                route.intent is AgentIntent.WHAT_IF
                and route.mutation_requested
                and not route.clarification.required
                and bool(route.operations or route.changes or route.operation == "clear")
            )
            if scenario_requested:
                schedule_result = self._run_tool(
                    conversation_id=conversation_id,
                    browser_workspace_id=browser_workspace_id,
                    message_id=user_message["message_id"],
                    owner_token=owner_token,
                    tool_name="preview_scenario",
                    inputs={
                        "conversation_id": conversation_id,
                        "target_week": target.week_start,
                        "changes": list(route.changes),
                        "operations": [item.model_dump(mode="json") for item in route.operations],
                        "employee_ids": list(route.employees),
                        "operation": route.operation,
                    },
                    trace=trace,
                )
                tool_output = schedule_result
                metadata["scenario_preview"] = dict(schedule_result)
                metadata["scenario_revision"] = schedule_result.get("scenario_revision", 0)
                if not schedule_result.get("strict_feasible", False):
                    metadata["infeasible_result"] = dict(schedule_result)
                metadata["suggestions"] = list(schedule_result.get("suggestions") or [])
            write_allowed = (
                route.intent in self.WRITE_INTENTS and route.mutation_requested
            )
            if save_scenario_requested:
                if current.get("draft") is not None:
                    pending = current["draft"]
                    raise DraftPendingError(target.week_start, pending["schedule_id"], pending["version"])
                schedule_result = self._run_tool(
                    conversation_id=conversation_id,
                    browser_workspace_id=browser_workspace_id,
                    message_id=user_message["message_id"],
                    owner_token=owner_token,
                    tool_name="save_scenario",
                    inputs={
                        "conversation_id": conversation_id,
                        "target_week": target.week_start,
                        "source_conversation_id": conversation_id,
                        "source_client_message_id": client_message_id,
                        "source_user_message_id": user_message["message_id"],
                        "_before_commit": lambda: self.conversations.renew_turn(
                            conversation_id,
                            browser_workspace_id,
                            message_id=user_message["message_id"],
                            owner_token=owner_token,
                        ),
                        "_turn_guard": (conversation_id, user_message["message_id"], owner_token),
                    },
                    trace=trace,
                )
                tool_output = schedule_result
                if schedule_result.get("status") == "feasible":
                    metadata["generated_draft_id"] = schedule_result.get("schedule_id")
                    metadata["generated_draft_version"] = schedule_result.get("version")
            elif write_allowed and not scenario_requested:
                if current.get("draft") is not None:
                    pending = current["draft"]
                    raise DraftPendingError(
                        target.week_start,
                        pending["schedule_id"],
                        pending["version"],
                    )
                changes = list(route.changes)
                if suggestion is not None and route.intent is AgentIntent.REPLAN:
                    changes, rebased = self._validate_suggestion_for_replan(
                        suggestion=suggestion,
                        target=target,
                        current=current,
                    )
                    metadata["version_guard"] = {
                        "based_on_schedule_id": suggestion.get("based_on_schedule_id"),
                        "based_on_version": suggestion.get("based_on_version"),
                        "rebased_to_schedule_id": (
                            current.get("confirmed") or {}
                        ).get("schedule_id"),
                        "rebased_to_version": (
                            current.get("confirmed") or {}
                        ).get("version"),
                        "revalidated": rebased,
                    }
                tool_name = (
                    "force_generate_schedule"
                    if route.force_generate
                    else "generate_schedule"
                    if route.intent is AgentIntent.GENERATE
                    else "replan_schedule"
                )
                if tool_name == "replan_schedule" and current.get("confirmed") is None:
                    route = route.model_copy(
                        update={
                            "intent": AgentIntent.CLARIFICATION,
                            "mutation_requested": False,
                            "clarification": AgentClarification(
                                required=True,
                                question="该周还没有正式排班。请确认是否先生成一版草稿。",
                            ),
                        }
                    )
                else:
                    inputs: dict[str, Any] = {
                        "target_week": target.week_start,
                        "changes": changes,
                        "source_conversation_id": conversation_id,
                        "source_client_message_id": client_message_id,
                        "source_user_message_id": user_message["message_id"],
                        "_before_commit": lambda: self.conversations.renew_turn(
                            conversation_id,
                            browser_workspace_id,
                            message_id=user_message["message_id"],
                            owner_token=owner_token,
                        ),
                        "_turn_guard": (
                            conversation_id,
                            user_message["message_id"],
                            owner_token,
                        ),
                    }
                    if tool_name == "replan_schedule":
                        inputs["minimize_changes"] = route.minimize_changes or True
                    elif tool_name == "force_generate_schedule":
                        confirmed_base = current.get("confirmed") or {}
                        inputs["expected_base"] = (confirmed_base.get("schedule_id"), confirmed_base.get("version"))
                        inputs["force_request"] = ForceRequest(
                            requested_overrides=route.requested_overrides,
                            forced_assignments=route.forced_assignments,
                            authorization_reason=route.authorization_reason or content,
                        )
                    schedule_result = self._run_tool(
                        conversation_id=conversation_id,
                        browser_workspace_id=browser_workspace_id,
                        message_id=user_message["message_id"],
                        owner_token=owner_token,
                        tool_name=tool_name,
                        inputs=inputs,
                        trace=trace,
                    )
                    tool_output = schedule_result
                    if schedule_result.get("status") == "feasible":
                        metadata["generated_draft_id"] = schedule_result.get("schedule_id")
                        metadata["generated_draft_version"] = schedule_result.get("version")
                        try:
                            current = self._run_tool(
                                conversation_id=conversation_id,
                                browser_workspace_id=browser_workspace_id,
                                message_id=user_message["message_id"],
                                owner_token=owner_token,
                                tool_name="get_current_schedule",
                                inputs={"target_week": target.week_start},
                                trace=trace,
                            )
                        except Exception:
                            current = self._current_after_draft(
                                current, schedule_result, target.week_start
                            )
                    elif schedule_result.get("status") == "infeasible":
                        # A failed first generation still establishes the
                        # conversation's scenario. Follow-up messages can then
                        # SET/ADD/REMOVE constraints even when no draft exists.
                        if route.changes and not route.force_generate:
                            schedule_result = self._run_tool(
                                conversation_id=conversation_id,
                                browser_workspace_id=browser_workspace_id,
                                message_id=user_message["message_id"],
                                owner_token=owner_token,
                                tool_name="preview_scenario",
                                inputs={
                                    "conversation_id": conversation_id,
                                    "target_week": target.week_start,
                                    "changes": list(route.changes),
                                    "employee_ids": list(route.employees),
                                    "operation": "add",
                                },
                                trace=trace,
                            )
                            tool_output = schedule_result
                            metadata["scenario_preview"] = dict(schedule_result)
                            metadata["scenario_revision"] = schedule_result.get("scenario_revision", 0)
                            metadata["suggestions"] = list(schedule_result.get("suggestions") or [])
                        if not schedule_result.get("strict_feasible", False):
                            metadata["infeasible_result"] = dict(schedule_result)
            elif route.intent is AgentIntent.ADVICE:
                tool_output = self._run_tool(
                    conversation_id=conversation_id,
                    browser_workspace_id=browser_workspace_id,
                    message_id=user_message["message_id"],
                    owner_token=owner_token,
                    tool_name="analyze_schedule",
                    inputs={
                        "target_week": target.week_start,
                        "changes": list(route.changes),
                    },
                    trace=trace,
                )
                metadata["suggestions"] = self._make_suggestions(
                    target, tool_output, current
                )
            elif route.intent is AgentIntent.VALIDATE:
                tool_output = self._run_tool(
                    conversation_id=conversation_id,
                    browser_workspace_id=browser_workspace_id,
                    message_id=user_message["message_id"],
                    owner_token=owner_token,
                    tool_name="validate_schedule",
                    inputs={"target_week": target.week_start},
                    trace=trace,
                )
            elif route.intent is AgentIntent.EXPLAIN:
                tool_output = self._run_tool(
                    conversation_id=conversation_id,
                    browser_workspace_id=browser_workspace_id,
                    message_id=user_message["message_id"],
                    owner_token=owner_token,
                    tool_name="get_schedule_context",
                    inputs={"target_week": target.week_start},
                    trace=trace,
                )
                if suggestion is not None:
                    metadata["referenced_suggestion"] = suggestion
            elif route.intent is AgentIntent.ASK:
                tool_output = self._run_tool(
                    conversation_id=conversation_id,
                    browser_workspace_id=browser_workspace_id,
                    message_id=user_message["message_id"],
                    owner_token=owner_token,
                    tool_name="get_schedule_context",
                    inputs={"target_week": target.week_start},
                    trace=trace,
                )

            if schedule_result and schedule_result.get("status") == "scenario_preview":
                revision = schedule_result.get("scenario_revision", 0)
                if schedule_result.get("strict_feasible"):
                    response_content = f"场景试排可行（场景版本 {revision}），结果仅供预览，未创建正式草稿。"
                else:
                    response_content = f"场景试排仍不可行（场景版本 {revision}）。我已返回最接近可行的试排结果和覆盖缺口，正式排班未改变。"
            elif schedule_result and schedule_result.get("status") == "feasible":
                exceptions = len(schedule_result.get("authorized_violations", []))
                response_content = (
                    f"已生成{target.iso_year}年第{target.iso_week}周排班草稿 "
                    f"v{schedule_result['version']}。"
                    + (f"其中有 {exceptions} 项已授权规则例外，请在工作台检查后手动确认。" if exceptions else "请在工作台检查后手动确认。")
                )
            elif schedule_result and schedule_result.get("status") == "infeasible":
                response_content = self._compose_infeasible_response(
                    schedule_result, target_week=target.week_start
                )
            elif schedule_result and schedule_result.get("status") == "clarification_required":
                response_content = schedule_result["clarification"]["prompt"]
            elif schedule_result and schedule_result.get("status") == "solver_unknown":
                response_content = schedule_result.get("message", "求解尚未完成，请重试。")
            else:
                response_content = self._compose_read_response(
                    route=route,
                    content=content,
                    target=target,
                    current=current,
                    tool_output=tool_output,
                    suggestion=suggestion,
                )
        except AIUnavailableError as exc:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="ai_unavailable",
                message=exc.safe_message,
                status_code=503,
                intent=route.intent.value,
                target_week=target.week_start,
                tool_calls=trace,
                error_details=exc.public_details,
            )
            raise AssertionError("unreachable")
        except DraftPendingError:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="draft_pending",
                message="当前周已有待确认草稿，请先确认或取消当前草稿。",
                status_code=409,
                intent=route.intent.value,
                target_week=target.week_start,
                tool_calls=trace,
            )
            raise AssertionError("unreachable")
        except HistoryUnavailableError:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="history_unavailable",
                message=(
                    "目标周缺少上一周已确认排班，因此无法安全校验连续工作天数和"
                    "晚班转早班规则。请补充上一周排班或选择连续的排班周次。"
                ),
                status_code=409,
                intent=route.intent.value,
                target_week=target.week_start,
                tool_calls=trace,
            )
            raise AssertionError("unreachable")
        except VersionConflictError:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="version_conflict",
                message="正式排班版本已变化，请刷新后重试。",
                status_code=409,
                intent=route.intent.value,
                target_week=target.week_start,
                tool_calls=trace,
            )
            raise AssertionError("unreachable")
        except StaleSuggestionError as exc:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="suggestion_stale",
                message=str(exc),
                status_code=409,
                intent=route.intent.value,
                target_week=target.week_start,
                tool_calls=trace,
            )
            raise AssertionError("unreachable")
        except WeekResolutionError as exc:
            response_content = exc.question
            route = AgentRoute(
                intent=AgentIntent.CLARIFICATION,
                mutation_requested=False,
                clarification={"required": True, "question": exc.question},
            )
            schedule_result = None
            metadata = {}
        except ValueError as exc:
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="invalid_agent_action",
                message=str(exc),
                status_code=422,
                intent=route.intent.value,
                target_week=target.week_start,
                tool_calls=trace,
            )
            raise AssertionError("unreachable")
        except ExecutionTimeout:
            raise
        except Exception:
            recovered = self._recover_incomplete_turn(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                user_message=user_message,
                owner_token=owner_token,
            )
            if recovered is not None:
                return self._replay_turn(recovered)
            self._complete_failure(
                conversation_id=conversation_id,
                browser_workspace_id=browser_workspace_id,
                client_message_id=client_message_id,
                owner_token=owner_token,
                user_message=user_message,
                code="agent_operation_failed",
                message="Agent 操作未完成，请稍后重试。",
                status_code=500,
                intent=route.intent.value,
                target_week=target.week_start,
                tool_calls=trace,
            )
            raise AssertionError("unreachable")

        display = current.get("display") if "current" in locals() else None
        confirmed = current.get("confirmed") if "current" in locals() else None
        context_payload = {
            **target.as_dict(),
            "display_schedule_id": (display or {}).get("schedule_id"),
            "display_schedule_version": (display or {}).get("version"),
            "confirmed_schedule_id": (confirmed or {}).get("schedule_id"),
            "confirmed_schedule_version": (confirmed or {}).get("version"),
        }
        metadata.update(
            {
                "target_week": target.week_start.isoformat(),
                "context": context_payload,
                "tool_call_ids": [item["tool_call_id"] for item in trace],
            }
        )
        summary_items = [
            f"用户近期目标：{content.strip()[:180]}",
            f"最近目标周：{target.week_start.isoformat()}",
            f"最近意图：{route.intent.value}",
            f"员工引用：{', '.join(route.employees) if route.employees else '无'}",
            (
                "排班引用："
                f"display={context_payload['display_schedule_id']}@"
                f"{context_payload['display_schedule_version']}，"
                f"confirmed={context_payload['confirmed_schedule_id']}@"
                f"{context_payload['confirmed_schedule_version']}"
            ),
        ]
        suggestion_ids = [
            str(item.get("suggestion_id") or item.get("id"))
            for item in metadata.get("suggestions", [])
            if isinstance(item, dict)
        ]
        if suggestion_ids:
            summary_items.append(f"最近建议：{', '.join(suggestion_ids)}")
        if route.clarification.required and route.clarification.question:
            summary_items.append(f"待澄清：{route.clarification.question}")
        previous_summary = (conversation or {}).get("summary")
        if previous_summary:
            summary_items.insert(0, f"既有摘要：{str(previous_summary)[-600:]}")
        summary = "；".join(summary_items)[-1400:]
        result = self.conversations.finalize_turn(
            conversation_id,
            browser_workspace_id,
            client_message_id=client_message_id,
            owner_token=owner_token,
            content=response_content,
            intent=route.intent.value,
            mutation_requested=(
                (route.intent in self.WRITE_INTENTS or route.intent is AgentIntent.WHAT_IF)
                and route.mutation_requested
            ),
            target_week=target.week_start,
            referenced_schedule_id=(display or {}).get("schedule_id"),
            referenced_version=(display or {}).get("version"),
            metadata=metadata,
            conversation_summary=summary,
            result_fields={
                "intent": route.intent.value,
                "mutation_requested": (
                    route.intent in self.WRITE_INTENTS and route.mutation_requested
                ),
                "context": context_payload,
                "tool_calls": trace,
                "schedule_result": schedule_result,
            },
        )
        return result
