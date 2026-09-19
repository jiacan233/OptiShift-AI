"""Fixed acceptance snapshots; no live application database or solver seeding."""
from datetime import date

from sqlalchemy import select

from backend.app.database import utc_now
from backend.app.models import Employee, WEEK_DAYS
from backend.app.models.orm import AssignmentRecord, Base, ScheduleRecord, SystemMetadataRecord
from backend.app.repository import ConversationRepository, EmployeeRepository, ScenarioRepository, ScheduleRepository
from backend.app.services.agent_service import AgentService
from backend.app.services.agent_tools import AgentTools
from backend.app.services.llm_client import AgentLLMClient
from backend.app.services.scheduling_service import SchedulingService

WEEK = date(2026, 10, 5)
MORNING = [[2, 3, 4, 5], [1, 2, 6, 16], [1, 4, 5, 15], [2, 3, 6, 16], [1, 4, 5, 15], [1, 2, 3, 6, 15, 16], [1, 2, 3, 4, 5, 6, 15]]
EVENING = [[7, 8, 9, 10], [11, 12, 13, 14], [7, 8, 11, 12], [9, 10, 13, 14], [7, 8, 11, 12], [7, 8, 9, 10, 13, 14], [7, 8, 9, 10, 11, 12]]
PREVIOUS_MESSAGES = [{"role": "assistant", "content": "恢复 E01 Mon 可用", "target_week": "2026-09-28", "metadata": {"suggestions": [
    {"id": "suggestion_1", "title": "恢复 E01 Mon 可用", "description": "请假限制影响覆盖", "target_week": "2026-09-28", "based_on_version": 1},
    {"id": "suggestion_2", "title": "检查员工可用日期", "description": "先核对可用日期再求解", "target_week": "2026-10-05", "based_on_version": 2},
]}}]


def seed_read_fixture(database):
    employees = EmployeeRepository(database)
    for i in range(1, 17):
        manager = i in {1, 2, 4, 8, 9, 12}
        employees.create(Employee(id=f"E{i:02d}", role="manager" if manager else "full_time",
                                  skills=["beverage", "cashier", *(["manager"] if manager else [])],
                                  available_days=list(WEEK_DAYS), leave_days=["Mon"] if i == 1 else []))
    with database.transaction() as session:
        session.add(SystemMetadataRecord(key="initial_known_empty_week", value=WEEK.isoformat()))
        for version in (1, 2):
            sid = f"sch_eval_v{version}"
            session.add(ScheduleRecord(schedule_id=sid, lineage_id="eval", version=version,
                                       status="confirmed", week_start=WEEK, validation_json={}, metadata_json={},
                                       created_at=utc_now(), confirmed_at=utc_now()))
            session.flush()
            for index, day in enumerate(WEEK_DAYS):
                for shift, groups in (("morning", MORNING), ("evening", EVENING)):
                    for i in groups[index]:
                        if version == 1 and day.value == "Sun" and shift == "morning" and i == 15:
                            continue
                        session.add(AssignmentRecord(schedule_id=sid, employee_id=f"E{i:02d}", day=day.value, shift=shift))
    schedules, scenarios = ScheduleRepository(database), ScenarioRepository(database)
    scheduling = SchedulingService(employees, schedules, scenarios=scenarios)
    tools = AgentTools(employees, schedules, scheduling, scenarios)
    llm = AgentLLMClient()
    llm.enabled = False
    return AgentService(ConversationRepository(database), employees, schedules, tools, llm=llm)


def database_snapshot(database, *, business_only=False):
    tables = [t for t in Base.metadata.sorted_tables if not business_only or t.name in {
        "schedules", "assignments", "employees", "conversation_scenarios", "system_metadata",
    }]
    with database.engine.connect() as connection:
        return {t.name: sorted((repr(tuple(row)) for row in connection.execute(select(t)))) for t in tables}
