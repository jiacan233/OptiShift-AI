from __future__ import annotations

from typing import Any

from ..database import database
from ..repository import (
    ConversationRepository,
    EmployeeRepository,
    ScenarioRepository,
    ScheduleRepository,
)
from ..services.agent_router import AgentRouter
from ..services.agent_service import AgentService
from ..services.agent_tools import AgentTools
from ..services.llm_client import AgentLLMClient
from ..services.scheduling_service import SchedulingService

employee_repository = EmployeeRepository(database)
schedule_repository = ScheduleRepository(database)
scenario_repository = ScenarioRepository(database)
agent_llm_client = AgentLLMClient()
scheduling_service = SchedulingService(
    employee_repository, schedule_repository, scenarios=scenario_repository
)
scheduling_service.intent_parser.llm = agent_llm_client
scheduling_service.explanations.llm = agent_llm_client
conversation_repository = ConversationRepository(database)
agent_router = AgentRouter(agent_llm_client)
agent_tools = AgentTools(employee_repository, schedule_repository, scheduling_service, scenario_repository)
agent_service = AgentService(
    conversation_repository,
    employee_repository,
    schedule_repository,
    agent_tools,
    router=agent_router,
    llm=agent_llm_client,
)

# Clarifications are short-lived UI interactions. Core schedules and versions remain in the
# configured persistent database.
pending_clarifications: dict[str, dict[str, Any]] = {}
