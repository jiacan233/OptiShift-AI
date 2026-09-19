from __future__ import annotations

import asyncio
import json
import time
from datetime import date
from queue import Empty, Full, Queue
from threading import Event
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..repository import ConversationBusyError, ConversationNotFoundError, TurnLeaseLostError
from ..services.agent_router import TrustedAgentAction
from ..services.agent_service import AgentTurnError
from .dependencies import agent_service

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversationBody(AgentApiModel):
    browser_workspace_id: str = Field(min_length=1, max_length=128)


class SendMessageBody(AgentApiModel):
    browser_workspace_id: str = Field(min_length=1, max_length=128)
    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=10_000)
    current_week_start: date | None = None
    trusted_action: TrustedAgentAction | None = None


@router.post("/conversations")
def create_conversation(body: CreateConversationBody) -> dict[str, Any]:
    return agent_service.create_conversation(body.browser_workspace_id)


@router.get("/conversations")
def list_conversations(
    browser_workspace_id: str = Query(min_length=1, max_length=128),
) -> dict[str, Any]:
    return {"conversations": agent_service.list_conversations(browser_workspace_id)}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    browser_workspace_id: str = Query(min_length=1, max_length=128),
) -> dict[str, Any]:
    result = agent_service.get_conversation(conversation_id, browser_workspace_id)
    if result.get("conversation") is None:
        raise ConversationNotFoundError(conversation_id)
    return result


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, body: SendMessageBody) -> dict[str, Any]:
    return agent_service.send_message(
        conversation_id=conversation_id,
        browser_workspace_id=body.browser_workspace_id,
        client_message_id=body.client_message_id,
        content=body.content,
        current_week_start=body.current_week_start,
        trusted_action=body.trusted_action,
    )


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(conversation_id: str, body: SendMessageBody, request: Request):
    """Disconnect detaches the observer; the single leased turn continues safely."""
    if not request.app.state.agent_slots.acquire(blocking=False):
        raise HTTPException(
            503, detail={"code": "conversation_busy", "message": "服务繁忙，请稍后重试。"}
        )
    queue: Queue = Queue(maxsize=256)
    detached = Event()

    def publish(kind, data):
        if detached.is_set():
            return
        try:
            queue.put_nowait((kind, data))
        except Full:
            # The final turn includes all execution facts if an observer is slow.
            try:
                queue.get_nowait()
            except Empty:
                pass
            queue.put_nowait((kind, data))

    def run():
        try:
            result = agent_service.send_message(
                conversation_id=conversation_id,
                **body.model_dump(exclude={"trusted_action"}),
                trusted_action=body.trusted_action,
                event_sink=lambda event: publish("execution", event),
            )
            publish("result", result)
        except AgentTurnError as exc:
            publish(
                "error",
                {
                    "code": exc.code,
                    "message": str(exc),
                    "status": exc.status_code,
                    "details": {**(exc.turn_result or {}), **(exc.details or {})},
                },
            )
        except (ConversationBusyError, TurnLeaseLostError):
            publish(
                "error",
                {
                    "code": "message_processing",
                    "status": 409,
                    "message": "请求仍在处理中，请使用同一请求标识重试。",
                },
            )
        except ConversationNotFoundError:
            publish(
                "error",
                {"code": "conversation_not_found", "status": 404, "message": "未找到当前对话。"},
            )
        except Exception:
            publish(
                "error",
                {
                    "code": "agent_operation_failed",
                    "status": 500,
                    "message": "处理未完成，请使用同一请求标识恢复。",
                },
            )
        finally:
            request.app.state.agent_slots.release()

    try:
        request.app.state.agent_executor.submit(run)
    except Exception:
        request.app.state.agent_slots.release()
        raise

    async def events():
        last_sent = time.monotonic()
        try:
            while True:
                try:
                    kind, data = queue.get_nowait()
                except Empty:
                    if time.monotonic() - last_sent >= 10:
                        yield "event: heartbeat\ndata: {}\n\n"
                        last_sent = time.monotonic()
                    await asyncio.sleep(0.05)
                    continue
                payload = json.dumps(jsonable_encoder(data), ensure_ascii=False)
                yield f"event: {kind}\ndata: {payload}\n\n"
                last_sent = time.monotonic()
                if kind in {"result", "error"}:
                    return
        finally:
            detached.set()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
