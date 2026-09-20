from __future__ import annotations

import asyncio

# Environment values must be loaded before modules create database/service singletons.
# ruff: noqa: E402
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import BoundedSemaphore
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from .api.agent import router as agent_router
from .api.dependencies import agent_llm_client, employee_repository
from .api.employees import router as employees_router
from .api.rules import router as rules_router
from .api.schedule import router as schedule_router
from .core import HistoryUnavailableError
from .database import database, initialize_database
from .repository import (
    ConversationBusyError,
    ConversationNotFoundError,
    DraftNotFoundError,
    DraftPendingError,
    EmployeeNotFoundError,
    ImmutableEmployeeFieldError,
    InvalidScheduleStateError,
    ScheduleNotFoundError,
    TurnLeaseLostError,
    VersionConflictError,
)
from .services.agent_service import AgentTurnError
from .services.agent_router import AgentRouter
from .services.llm_client import AIUnavailableError
from .services.request_validator import BusinessValidationError
from .services.scheduling_service import SolverOutputError

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("optishift.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    _app.state.agent_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent-turn")
    _app.state.agent_slots = BoundedSemaphore(8)
    try:
        yield
    finally:
        await asyncio.to_thread(_app.state.agent_executor.shutdown, wait=True)
        agent_llm_client.close()


app = FastAPI(
    title="OptiShift AI Workforce Scheduling Agent",
    version="0.1.0",
    lifespan=lifespan,
)

origins = [
    item.strip()
    for item in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed request_id=%s operation=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        raise
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_complete request_id=%s operation=%s path=%s status=%s duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


def problem(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=jsonable_encoder(
            {"error": {"code": code, "message": message, "details": details}}
        ),
    )


from pydantic import ValidationError
from .services.agent_service import map_agent_error


@app.exception_handler(ValidationError)
async def model_validation_error(_request: Request, exc: ValidationError):
    logger.exception("model_validation_failed")
    error = map_agent_error(exc)
    return problem(error["status"], error["code"], error["message"])


@app.exception_handler(RequestValidationError)
async def request_validation_error(_request: Request, exc: RequestValidationError):
    return problem(422, "clarification_required", "请求内容不完整，请检查员工、日期和班次后重试。")


@app.exception_handler(VersionConflictError)
async def version_conflict(_request: Request, exc: VersionConflictError):
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(DraftPendingError)
async def draft_pending(_request: Request, exc: DraftPendingError):
    return problem(
        409,
        "draft_pending",
        "A pending draft already exists for this week.",
        {
            "week_start": exc.week_start.isoformat(),
            "schedule_id": exc.schedule_id,
            "version": exc.version,
        },
    )


@app.exception_handler(AgentTurnError)
async def agent_turn_error(_request: Request, exc: AgentTurnError):
    details = dict(exc.turn_result or {})
    details.update(exc.details or {})
    return problem(exc.status_code, exc.code, str(exc), details or None)


@app.exception_handler(AIUnavailableError)
async def ai_unavailable(_request: Request, exc: AIUnavailableError):
    return problem(503, "ai_unavailable", exc.safe_message, exc.public_details)


@app.exception_handler(ConversationNotFoundError)
async def conversation_not_found(_request: Request, _exc: ConversationNotFoundError):
    return problem(404, "conversation_not_found", "Conversation was not found.")


@app.exception_handler(ConversationBusyError)
async def conversation_busy(_request: Request, _exc: ConversationBusyError):
    return problem(
        409,
        "conversation_busy",
        "Another message in this conversation is still being processed.",
    )


@app.exception_handler(TurnLeaseLostError)
async def turn_lease_lost(_request: Request, _exc: TurnLeaseLostError):
    return problem(
        409,
        "message_processing",
        "This message was recovered by another request and is still being processed.",
    )


@app.exception_handler(ScheduleNotFoundError)
@app.exception_handler(DraftNotFoundError)
@app.exception_handler(EmployeeNotFoundError)
async def not_found(_request: Request, exc: Exception):
    return problem(
        404,
        "entity_not_found",
        "The requested employee or schedule was not found.",
        str(exc),
    )


@app.exception_handler(HistoryUnavailableError)
async def history_unavailable(_request: Request, exc: HistoryUnavailableError):
    return problem(409, "history_unavailable", str(exc))


@app.exception_handler(BusinessValidationError)
async def business_validation(_request: Request, exc: BusinessValidationError):
    return problem(422, "validation_error", str(exc), exc.errors)


@app.exception_handler(ImmutableEmployeeFieldError)
@app.exception_handler(InvalidScheduleStateError)
@app.exception_handler(ValueError)
async def invalid_operation(_request: Request, exc: Exception):
    return problem(422, "validation_error", "请求条件无效，请检查后重试。")


@app.exception_handler(SolverOutputError)
async def solver_output_error(_request: Request, exc: SolverOutputError):
    logger.exception("solver_validation_failed")
    return problem(500, "agent_internal_error", "排班服务暂时异常，请稍后重试。")


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.exception(
        "unhandled_error request_id=%s path=%s",
        getattr(request.state, "request_id", "unknown"),
        request.url.path,
    )
    return problem(500, "internal_error", "An unexpected server error occurred.")


@app.get("/health", tags=["system"])
def health(response: Response) -> dict:
    healthy = database.is_healthy()
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "app": "optishift-ai", "database": healthy}


@app.get("/health/llm", tags=["system"])
def llm_health(response: Response) -> dict:
    result = agent_llm_client.health_check()
    if result.get("status") != "error":
        probe = AgentRouter(agent_llm_client).probe(employees=employee_repository.list())
        result["checks"]["agent_router"] = probe
        if probe["status"] != "ok":
            result["status"] = "degraded"
    if result.get("status") != "ok":
        response.status_code = 503
    return result


@app.get("/health/agent-router", tags=["system"])
def agent_router_health(response: Response) -> dict:
    result = AgentRouter(agent_llm_client).probe(employees=employee_repository.list())
    if result["status"] != "ok":
        response.status_code = 503
    return result


app.include_router(employees_router)
app.include_router(rules_router)
app.include_router(schedule_router)
app.include_router(agent_router)

frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
