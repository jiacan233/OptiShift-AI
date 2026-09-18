from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import Database, utc_now
from ..models.orm import (
    AgentToolCallRecord,
    ConversationMessageRecord,
    ConversationRecord,
)


class ConversationNotFoundError(LookupError):
    pass


class ConversationBusyError(RuntimeError):
    pass


class TurnLeaseLostError(RuntimeError):
    pass


class MessageNotFoundError(LookupError):
    pass


class ToolCallNotFoundError(LookupError):
    pass


_UNSET = object()


class ConversationRepository:
    """Persistence boundary for browser-scoped conversations and audit traces."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    @staticmethod
    def _as_date(value: date | str | None) -> date | None:
        if value is None or isinstance(value, date):
            return value
        return date.fromisoformat(value)

    @staticmethod
    def _utc_iso(value: datetime) -> str:
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat()

    @staticmethod
    def _next_sequence(
        session: Session,
        model: type[ConversationMessageRecord] | type[AgentToolCallRecord],
        conversation_id: str,
    ) -> int:
        current = session.scalar(
            select(func.max(model.sequence_number)).where(
                model.conversation_id == conversation_id
            )
        )
        return int(current or 0) + 1

    @staticmethod
    def _lease_expired(
        started_at: datetime, timestamp: datetime, stale_after: timedelta
    ) -> bool:
        normalized_started = (
            started_at.replace(tzinfo=UTC)
            if started_at.tzinfo is None
            else started_at.astimezone(UTC)
        )
        normalized_now = (
            timestamp.replace(tzinfo=UTC)
            if timestamp.tzinfo is None
            else timestamp.astimezone(UTC)
        )
        return normalized_now - normalized_started >= stale_after

    @staticmethod
    def _require_turn_owner(
        conversation: ConversationRecord,
        message_id: str,
        owner_token: str,
    ) -> None:
        if (
            conversation.active_turn_message_id != message_id
            or conversation.active_turn_owner_token != owner_token
        ):
            raise TurnLeaseLostError(message_id)

    @staticmethod
    def _conversation_dict(record: ConversationRecord) -> dict[str, Any]:
        return {
            "conversation_id": record.conversation_id,
            "browser_workspace_id": record.browser_workspace_id,
            "title": record.title,
            "summary": record.summary,
            "status": record.status,
            "created_at": ConversationRepository._utc_iso(record.created_at),
            "updated_at": ConversationRepository._utc_iso(record.updated_at),
        }

    @staticmethod
    def _message_dict(record: ConversationMessageRecord) -> dict[str, Any]:
        metadata = dict(record.metadata_json or {})
        return {
            "message_id": record.message_id,
            "conversation_id": record.conversation_id,
            "sequence_number": record.sequence_number,
            "client_message_id": record.client_message_id,
            "role": record.role,
            "content": record.content,
            "intent": record.intent,
            "mutation_requested": record.mutation_requested,
            "target_week": (
                record.target_week.isoformat() if record.target_week else None
            ),
            "referenced_schedule_id": record.referenced_schedule_id,
            "referenced_version": record.referenced_version,
            "metadata": metadata,
            "metadata_json": metadata,
            "created_at": ConversationRepository._utc_iso(record.created_at),
        }

    @staticmethod
    def _tool_call_dict(record: AgentToolCallRecord) -> dict[str, Any]:
        return {
            "tool_call_id": record.tool_call_id,
            "conversation_id": record.conversation_id,
            "sequence_number": record.sequence_number,
            "message_id": record.message_id,
            "tool_name": record.tool_name,
            "input": record.input_json,
            "output": record.output_json,
            "input_json": record.input_json,
            "output_json": record.output_json,
            "status": record.status,
            "created_at": ConversationRepository._utc_iso(record.created_at),
            "finished_at": (
                ConversationRepository._utc_iso(record.finished_at)
                if record.finished_at
                else None
            ),
        }

    @staticmethod
    def _validate_workspace_id(browser_workspace_id: str) -> str:
        value = browser_workspace_id.strip()
        if not value:
            raise ValueError("browser_workspace_id is required")
        if len(value) > 128:
            raise ValueError("browser_workspace_id must be at most 128 characters")
        return value

    @staticmethod
    def _owned_conversation(
        session: Session,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        lock: bool = False,
    ) -> ConversationRecord | None:
        statement = select(ConversationRecord).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.browser_workspace_id == browser_workspace_id,
        )
        if lock and session.bind is not None and session.bind.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    @classmethod
    def _require_owned_conversation(
        cls,
        session: Session,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        lock: bool = False,
    ) -> ConversationRecord:
        record = cls._owned_conversation(
            session,
            conversation_id,
            browser_workspace_id,
            lock=lock,
        )
        if record is None:
            # Deliberately does not reveal whether the conversation exists for a
            # different anonymous browser workspace.
            raise ConversationNotFoundError(conversation_id)
        return record

    def create_conversation(
        self,
        browser_workspace_id: str,
        *,
        conversation_id: str | None = None,
        title: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        timestamp = utc_now()
        record = ConversationRecord(
            conversation_id=conversation_id or self._new_id("conv"),
            browser_workspace_id=workspace_id,
            title=title,
            summary=summary,
            status="active",
            active_turn_message_id=None,
            active_turn_owner_token=None,
            active_turn_started_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self.database.transaction(immediate=True) as session:
            session.add(record)
            session.flush()
            return self._conversation_dict(record)

    def list_conversations(
        self,
        browser_workspace_id: str,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        if status not in {None, "active", "archived"}:
            raise ValueError("status must be active or archived")

        statement = select(ConversationRecord).where(
            ConversationRecord.browser_workspace_id == workspace_id
        )
        if status is not None:
            statement = statement.where(ConversationRecord.status == status)
        statement = statement.order_by(
            ConversationRecord.updated_at.desc(),
            ConversationRecord.conversation_id.desc(),
        )

        with self.database.transaction() as session:
            records = session.scalars(statement).all()
            results: list[dict[str, Any]] = []
            for record in records:
                message_count = session.scalar(
                    select(func.count(ConversationMessageRecord.message_id)).where(
                        ConversationMessageRecord.conversation_id
                        == record.conversation_id
                    )
                )
                last_message = session.scalar(
                    select(ConversationMessageRecord)
                    .where(
                        ConversationMessageRecord.conversation_id
                        == record.conversation_id
                    )
                    .order_by(
                        ConversationMessageRecord.sequence_number.desc(),
                    )
                    .limit(1)
                )
                last_target_week = session.scalar(
                    select(ConversationMessageRecord.target_week)
                    .where(
                        ConversationMessageRecord.conversation_id
                        == record.conversation_id,
                        ConversationMessageRecord.target_week.is_not(None),
                    )
                    .order_by(
                        ConversationMessageRecord.sequence_number.desc(),
                    )
                    .limit(1)
                )
                item = self._conversation_dict(record)
                item.update(
                    {
                        "message_count": int(message_count or 0),
                        "last_message_preview": (
                            last_message.content[:160] if last_message else None
                        ),
                        "target_week": (
                            last_target_week.isoformat()
                            if last_target_week is not None
                            else None
                        ),
                    }
                )
                results.append(item)
            return results

    def get_conversation(
        self,
        conversation_id: str,
        browser_workspace_id: str,
    ) -> dict[str, Any] | None:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction() as session:
            record = self._owned_conversation(
                session, conversation_id, workspace_id
            )
            return self._conversation_dict(record) if record is not None else None

    def update_conversation(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        title: str | None | object = _UNSET,
        summary: str | None | object = _UNSET,
        status: str | object = _UNSET,
    ) -> dict[str, Any]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        if status is not _UNSET and status not in {"active", "archived"}:
            raise ValueError("status must be active or archived")

        with self.database.transaction(immediate=True) as session:
            record = self._require_owned_conversation(
                session,
                conversation_id,
                workspace_id,
                lock=True,
            )
            if title is not _UNSET:
                record.title = title  # type: ignore[assignment]
            if summary is not _UNSET:
                record.summary = summary  # type: ignore[assignment]
            if status is not _UNSET:
                record.status = status  # type: ignore[assignment]
            record.updated_at = utc_now()
            session.flush()
            return self._conversation_dict(record)

    def list_messages(
        self,
        conversation_id: str,
        browser_workspace_id: str,
    ) -> list[dict[str, Any]]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction() as session:
            self._require_owned_conversation(
                session, conversation_id, workspace_id
            )
            records = session.scalars(
                select(ConversationMessageRecord)
                .where(
                    ConversationMessageRecord.conversation_id == conversation_id
                )
                .order_by(
                    ConversationMessageRecord.sequence_number,
                )
            ).all()
            return [self._message_dict(record) for record in records]

    def find_user_by_client_message_id(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        client_message_id: str,
    ) -> dict[str, Any] | None:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction() as session:
            self._require_owned_conversation(
                session, conversation_id, workspace_id
            )
            record = session.scalar(
                select(ConversationMessageRecord).where(
                    ConversationMessageRecord.conversation_id == conversation_id,
                    ConversationMessageRecord.client_message_id == client_message_id,
                    ConversationMessageRecord.role == "user",
                )
            )
            return self._message_dict(record) if record is not None else None

    def add_user_message(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        client_message_id: str,
        content: str,
        target_week: date | str | None = None,
        metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
    ) -> tuple[dict[str, Any], bool, str | None]:
        """Claim a client action once, returning message, created, and lease owner."""

        workspace_id = self._validate_workspace_id(browser_workspace_id)
        if not client_message_id.strip():
            raise ValueError("client_message_id is required")
        if len(client_message_id) > 128:
            raise ValueError("client_message_id must be at most 128 characters")
        if not content.strip():
            raise ValueError("message content is required")

        timestamp = utc_now()
        payload_metadata = dict(metadata or {})
        payload_metadata.setdefault("turn_status", "processing")
        try:
            with self.database.transaction(immediate=True) as session:
                conversation = self._require_owned_conversation(
                    session,
                    conversation_id,
                    workspace_id,
                    lock=True,
                )
                existing = session.scalar(
                    select(ConversationMessageRecord).where(
                        ConversationMessageRecord.conversation_id == conversation_id,
                        ConversationMessageRecord.client_message_id == client_message_id,
                        ConversationMessageRecord.role == "user",
                    )
                )
                if existing is not None:
                    return self._message_dict(existing), False, None
                if conversation.active_turn_message_id is not None:
                    raise ConversationBusyError(conversation_id)
                owner_token = self._new_id("lease")
                record = ConversationMessageRecord(
                    message_id=message_id or self._new_id("msg"),
                    conversation_id=conversation_id,
                    sequence_number=self._next_sequence(
                        session, ConversationMessageRecord, conversation_id
                    ),
                    client_message_id=client_message_id,
                    role="user",
                    content=content,
                    intent=None,
                    mutation_requested=False,
                    target_week=self._as_date(target_week),
                    referenced_schedule_id=None,
                    referenced_version=None,
                    metadata_json=payload_metadata,
                    created_at=timestamp,
                )
                session.add(record)
                conversation.active_turn_message_id = record.message_id
                conversation.active_turn_owner_token = owner_token
                conversation.active_turn_started_at = timestamp
                conversation.updated_at = timestamp
                session.flush()
                return self._message_dict(record), True, owner_token
        except IntegrityError:
            existing = self.find_user_by_client_message_id(
                conversation_id,
                workspace_id,
                client_message_id,
            )
            if existing is None:
                raise
            return existing, False, None

    def reclaim_turn(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        client_message_id: str,
        stale_after: timedelta,
    ) -> str | None:
        """Claim an unfinished idempotent turn after its processing lease expires."""

        workspace_id = self._validate_workspace_id(browser_workspace_id)
        timestamp = utc_now()
        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session, conversation_id, workspace_id, lock=True
            )
            statement = select(ConversationMessageRecord).where(
                ConversationMessageRecord.conversation_id == conversation_id,
                ConversationMessageRecord.client_message_id == client_message_id,
                ConversationMessageRecord.role == "user",
            )
            if session.bind is not None and session.bind.dialect.name != "sqlite":
                statement = statement.with_for_update()
            user = session.scalar(statement)
            if user is None:
                raise MessageNotFoundError(client_message_id)
            if isinstance(dict(user.metadata_json or {}).get("turn_result"), dict):
                return None
            active_id = conversation.active_turn_message_id
            if active_id not in {None, user.message_id}:
                return None
            started_at = conversation.active_turn_started_at or user.created_at
            if not self._lease_expired(started_at, timestamp, stale_after):
                return None
            owner_token = self._new_id("lease")
            conversation.active_turn_message_id = user.message_id
            conversation.active_turn_owner_token = owner_token
            conversation.active_turn_started_at = timestamp
            conversation.updated_at = timestamp
            session.flush()
            return owner_token

    def claim_stale_active_turn(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        stale_after: timedelta,
    ) -> tuple[dict[str, Any], str] | None:
        """Take ownership of a stale turn so it can be recovered or terminated."""

        workspace_id = self._validate_workspace_id(browser_workspace_id)
        timestamp = utc_now()
        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session, conversation_id, workspace_id, lock=True
            )
            message_id = conversation.active_turn_message_id
            started_at = conversation.active_turn_started_at
            if message_id is None or started_at is None:
                return None
            if not self._lease_expired(started_at, timestamp, stale_after):
                return None
            user = session.get(ConversationMessageRecord, message_id)
            if user is None or user.conversation_id != conversation_id or user.role != "user":
                raise MessageNotFoundError(message_id)
            owner_token = self._new_id("lease")
            conversation.active_turn_owner_token = owner_token
            conversation.active_turn_started_at = timestamp
            conversation.updated_at = timestamp
            session.flush()
            return self._message_dict(user), owner_token

    def renew_turn(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        message_id: str,
        owner_token: str,
    ) -> None:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session, conversation_id, workspace_id, lock=True
            )
            self._require_turn_owner(conversation, message_id, owner_token)
            conversation.active_turn_started_at = utc_now()
            session.flush()

    def add_assistant_message(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        content: str,
        intent: str | None = None,
        mutation_requested: bool = False,
        target_week: date | str | None = None,
        referenced_schedule_id: str | None = None,
        referenced_version: int | None = None,
        metadata: dict[str, Any] | None = None,
        in_reply_to_message_id: str | None = None,
        turn_result: dict[str, Any] | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        if not content.strip():
            raise ValueError("message content is required")

        payload_metadata = dict(metadata or {})
        if in_reply_to_message_id is not None:
            payload_metadata["in_reply_to_message_id"] = in_reply_to_message_id
        if turn_result is not None:
            payload_metadata["turn_result"] = turn_result
        timestamp = utc_now()

        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session,
                conversation_id,
                workspace_id,
                lock=True,
            )
            if in_reply_to_message_id is not None:
                source = session.get(
                    ConversationMessageRecord, in_reply_to_message_id
                )
                if (
                    source is None
                    or source.conversation_id != conversation_id
                    or source.role != "user"
                ):
                    raise MessageNotFoundError(in_reply_to_message_id)
            record = ConversationMessageRecord(
                message_id=message_id or self._new_id("msg"),
                conversation_id=conversation_id,
                sequence_number=self._next_sequence(
                    session, ConversationMessageRecord, conversation_id
                ),
                client_message_id=None,
                role="assistant",
                content=content,
                intent=intent,
                mutation_requested=mutation_requested,
                target_week=self._as_date(target_week),
                referenced_schedule_id=referenced_schedule_id,
                referenced_version=referenced_version,
                metadata_json=payload_metadata,
                created_at=timestamp,
            )
            session.add(record)
            conversation.updated_at = timestamp
            session.flush()
            return self._message_dict(record)

    def finalize_turn(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        client_message_id: str,
        owner_token: str,
        content: str,
        result_fields: dict[str, Any],
        intent: str | None = None,
        mutation_requested: bool = False,
        target_week: date | str | None = None,
        referenced_schedule_id: str | None = None,
        referenced_version: int | None = None,
        metadata: dict[str, Any] | None = None,
        assistant_message_id: str | None = None,
        conversation_summary: str | None = None,
    ) -> dict[str, Any]:
        """Persist the assistant reply and replayable turn result atomically."""

        workspace_id = self._validate_workspace_id(browser_workspace_id)
        if not content.strip():
            raise ValueError("message content is required")
        timestamp = utc_now()
        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session,
                conversation_id,
                workspace_id,
                lock=True,
            )
            statement = select(ConversationMessageRecord).where(
                ConversationMessageRecord.conversation_id == conversation_id,
                ConversationMessageRecord.client_message_id == client_message_id,
                ConversationMessageRecord.role == "user",
            )
            if session.bind is not None and session.bind.dialect.name != "sqlite":
                statement = statement.with_for_update()
            user = session.scalar(statement)
            if user is None:
                raise MessageNotFoundError(client_message_id)
            self._require_turn_owner(conversation, user.message_id, owner_token)
            existing = dict(user.metadata_json or {}).get("turn_result")
            if isinstance(existing, dict):
                conversation.active_turn_message_id = None
                conversation.active_turn_owner_token = None
                conversation.active_turn_started_at = None
                conversation.updated_at = timestamp
                session.flush()
                return existing

            assistant_metadata = dict(metadata or {})
            assistant_metadata["in_reply_to_message_id"] = user.message_id
            assistant = ConversationMessageRecord(
                message_id=assistant_message_id or self._new_id("msg"),
                conversation_id=conversation_id,
                sequence_number=self._next_sequence(
                    session, ConversationMessageRecord, conversation_id
                ),
                client_message_id=None,
                role="assistant",
                content=content,
                intent=intent,
                mutation_requested=mutation_requested,
                target_week=self._as_date(target_week),
                referenced_schedule_id=referenced_schedule_id,
                referenced_version=referenced_version,
                metadata_json=assistant_metadata,
                created_at=timestamp,
            )
            session.add(assistant)
            session.flush()
            result = {
                **result_fields,
                "user_message": self._message_dict(user),
                "assistant_message": self._message_dict(assistant),
            }
            user.metadata_json = {
                **dict(user.metadata_json or {}),
                "turn_status": "completed",
                "turn_result": result,
            }
            if not conversation.title:
                conversation.title = user.content.strip()[:60]
            if conversation_summary is not None:
                conversation.summary = conversation_summary
            elif not conversation.summary and result_fields.get("error"):
                conversation.summary = f"最近请求：{user.content.strip()[:180]}；结果：{content[:240]}"
            if conversation.active_turn_message_id == user.message_id:
                conversation.active_turn_message_id = None
                conversation.active_turn_owner_token = None
                conversation.active_turn_started_at = None
            conversation.updated_at = timestamp
            session.flush()
            return result

    def update_message(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        message_id: str,
        *,
        intent: str | None | object = _UNSET,
        mutation_requested: bool | object = _UNSET,
        target_week: date | str | None | object = _UNSET,
        referenced_schedule_id: str | None | object = _UNSET,
        referenced_version: int | None | object = _UNSET,
        metadata: dict[str, Any] | object = _UNSET,
        turn_owner_token: str | None = None,
    ) -> dict[str, Any]:
        """Persist resolved routing/context fields after a user turn is parsed."""

        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session,
                conversation_id,
                workspace_id,
                lock=True,
            )
            statement = select(ConversationMessageRecord).where(
                ConversationMessageRecord.message_id == message_id,
                ConversationMessageRecord.conversation_id == conversation_id,
            )
            if session.bind is not None and session.bind.dialect.name != "sqlite":
                statement = statement.with_for_update()
            record = session.scalar(statement)
            if record is None:
                raise MessageNotFoundError(message_id)
            if record.role != "user":
                raise ValueError("Only user messages can be annotated with routing results")
            if turn_owner_token is not None:
                self._require_turn_owner(
                    conversation, record.message_id, turn_owner_token
                )
            if intent is not _UNSET:
                record.intent = intent  # type: ignore[assignment]
            if mutation_requested is not _UNSET:
                record.mutation_requested = bool(mutation_requested)
            if target_week is not _UNSET:
                record.target_week = self._as_date(target_week)  # type: ignore[arg-type]
            if referenced_schedule_id is not _UNSET:
                record.referenced_schedule_id = referenced_schedule_id  # type: ignore[assignment]
            if referenced_version is not _UNSET:
                record.referenced_version = referenced_version  # type: ignore[assignment]
            if metadata is not _UNSET:
                record.metadata_json = {
                    **dict(record.metadata_json or {}),
                    **dict(metadata),  # type: ignore[arg-type]
                }
            session.flush()
            return self._message_dict(record)

    def annotate_user_message(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        message_id: str,
        *,
        intent: str,
        mutation_requested: bool,
        target_week: date | str | None,
        referenced_schedule_id: str | None = None,
        referenced_version: int | None = None,
        metadata: dict[str, Any] | None = None,
        owner_token: str | None = None,
    ) -> dict[str, Any]:
        message = self.update_message(
            conversation_id,
            browser_workspace_id,
            message_id,
            intent=intent,
            mutation_requested=mutation_requested,
            target_week=target_week,
            referenced_schedule_id=referenced_schedule_id,
            referenced_version=referenced_version,
            metadata=metadata or {},
            turn_owner_token=owner_token,
        )
        return message

    def get_idempotent_turn_result(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        client_message_id: str,
    ) -> dict[str, Any] | None:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction() as session:
            self._require_owned_conversation(
                session, conversation_id, workspace_id
            )
            user = session.scalar(
                select(ConversationMessageRecord).where(
                    ConversationMessageRecord.conversation_id == conversation_id,
                    ConversationMessageRecord.client_message_id == client_message_id,
                    ConversationMessageRecord.role == "user",
                )
            )
            if user is None:
                return None
            metadata = dict(user.metadata_json or {})
            turn_result = metadata.get("turn_result")
            if isinstance(turn_result, dict):
                return turn_result

            # Backward-compatible lookup when the result was stored with the
            # assistant response instead of the user claim record.
            assistants = session.scalars(
                select(ConversationMessageRecord)
                .where(
                    ConversationMessageRecord.conversation_id == conversation_id,
                    ConversationMessageRecord.role == "assistant",
                    ConversationMessageRecord.created_at >= user.created_at,
                )
                .order_by(
                    ConversationMessageRecord.sequence_number,
                )
            ).all()
            for assistant in assistants:
                assistant_metadata = dict(assistant.metadata_json or {})
                if (
                    assistant_metadata.get("in_reply_to_message_id")
                    == user.message_id
                    and isinstance(assistant_metadata.get("turn_result"), dict)
                ):
                    return assistant_metadata["turn_result"]
            return None

    def complete_idempotent_turn(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        client_message_id: str,
        turn_result: dict[str, Any],
    ) -> dict[str, Any]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction(immediate=True) as session:
            self._require_owned_conversation(
                session,
                conversation_id,
                workspace_id,
                lock=True,
            )
            statement = select(ConversationMessageRecord).where(
                ConversationMessageRecord.conversation_id == conversation_id,
                ConversationMessageRecord.client_message_id == client_message_id,
                ConversationMessageRecord.role == "user",
            )
            if session.bind is not None and session.bind.dialect.name != "sqlite":
                statement = statement.with_for_update()
            record = session.scalar(statement)
            if record is None:
                raise MessageNotFoundError(client_message_id)
            record.metadata_json = {
                **dict(record.metadata_json or {}),
                "turn_status": "completed",
                "turn_result": turn_result,
            }
            session.flush()
            return self._message_dict(record)

    def add_tool_call(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        message_id: str,
        tool_name: str,
        input_json: dict[str, Any],
        owner_token: str,
        status: str = "running",
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        if status not in {"running", "completed", "failed"}:
            raise ValueError("invalid tool call status")
        timestamp = utc_now()
        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session,
                conversation_id,
                workspace_id,
                lock=True,
            )
            message = session.get(ConversationMessageRecord, message_id)
            if message is None or message.conversation_id != conversation_id:
                raise MessageNotFoundError(message_id)
            self._require_turn_owner(conversation, message_id, owner_token)
            conversation.active_turn_started_at = timestamp
            record = AgentToolCallRecord(
                tool_call_id=tool_call_id or self._new_id("tool"),
                conversation_id=conversation_id,
                sequence_number=self._next_sequence(
                    session, AgentToolCallRecord, conversation_id
                ),
                message_id=message_id,
                tool_name=tool_name,
                input_json=dict(input_json),
                output_json=None,
                status=status,
                created_at=timestamp,
                finished_at=timestamp if status != "running" else None,
            )
            session.add(record)
            session.flush()
            return self._tool_call_dict(record)

    def finish_tool_call(
        self,
        tool_call_id: str,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        output_json: Any = None,
        status: str = "completed",
        owner_token: str,
    ) -> dict[str, Any]:
        if status not in {"completed", "failed"}:
            raise ValueError("finished tool call status must be completed or failed")
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction(immediate=True) as session:
            conversation = self._require_owned_conversation(
                session,
                conversation_id,
                workspace_id,
                lock=True,
            )
            statement = select(AgentToolCallRecord).where(
                AgentToolCallRecord.tool_call_id == tool_call_id,
                AgentToolCallRecord.conversation_id == conversation_id,
            )
            if session.bind is not None and session.bind.dialect.name != "sqlite":
                statement = statement.with_for_update()
            record = session.scalar(statement)
            if record is None:
                raise ToolCallNotFoundError(tool_call_id)
            self._require_turn_owner(
                conversation, record.message_id, owner_token
            )
            conversation.active_turn_started_at = utc_now()
            record.output_json = output_json
            record.status = status
            record.finished_at = utc_now()
            session.flush()
            return self._tool_call_dict(record)

    def list_tool_calls(
        self,
        conversation_id: str,
        browser_workspace_id: str,
        *,
        message_id: str | None = None,
    ) -> list[dict[str, Any]]:
        workspace_id = self._validate_workspace_id(browser_workspace_id)
        with self.database.transaction() as session:
            self._require_owned_conversation(
                session, conversation_id, workspace_id
            )
            statement = select(AgentToolCallRecord).where(
                AgentToolCallRecord.conversation_id == conversation_id
            )
            if message_id is not None:
                statement = statement.where(
                    AgentToolCallRecord.message_id == message_id
                )
            records = session.scalars(
                statement.order_by(
                    AgentToolCallRecord.sequence_number,
                )
            ).all()
            return [self._tool_call_dict(record) for record in records]
