from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from ..repository import ConversationNotFoundError
from ..services.agent_router import TrustedAgentAction
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
    return {
        "conversations": agent_service.list_conversations(browser_workspace_id)
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    browser_workspace_id: str = Query(min_length=1, max_length=128),
) -> dict[str, Any]:
    result = agent_service.get_conversation(
        conversation_id, browser_workspace_id
    )
    if result.get("conversation") is None:
        raise ConversationNotFoundError(conversation_id)
    return result


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str, body: SendMessageBody
) -> dict[str, Any]:
    return agent_service.send_message(
        conversation_id=conversation_id,
        browser_workspace_id=body.browser_workspace_id,
        client_message_id=body.client_message_id,
        content=body.content,
        current_week_start=body.current_week_start,
        trusted_action=body.trusted_action,
    )
