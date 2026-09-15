import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from cortex_ai import (
    MAX_ASSISTANT_RESPONSE_CHARACTERS,
    AssistantTextDelta,
    ChatMessage,
    ChatModel,
    ChatTurnResponse,
    InvalidModelOutput,
    ModelResponse,
    ModelStreamCompleted,
    TokenUsage,
)
from cortex_state import (
    AsyncSessionFactory,
    ConversationRepository,
    StaleConversationError,
    async_session_scope,
)


class ConversationNotFound(Exception):
    pass


class ConversationHistoryFull(Exception):
    pass


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    id: uuid.UUID
    sequence: int
    role: str
    content: str
    created_at: datetime


class ConversationResponse(ConversationSummary):
    messages: list[ConversationMessageResponse]


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    limit: int
    offset: int


class AppendTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)
    ]


class AppendTurnResponse(BaseModel):
    conversation: ConversationResponse
    model: str
    usage: TokenUsage | None = None


class ConversationTextDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: Annotated[str, StringConstraints(min_length=1)]


class ConversationStreamCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    conversation: ConversationResponse
    model: str
    usage: TokenUsage | None = None


class ConversationStreamError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    error: Literal[
        "conversation_not_found",
        "conversation_conflict",
        "conversation_history_full",
        "model_timeout",
        "model_unavailable",
        "invalid_model_response",
        "model_rejected_request",
        "conversation_error",
    ]


class ConversationService:
    def __init__(self, session_factory: AsyncSessionFactory, model: ChatModel) -> None:
        self._session_factory = session_factory
        self._model = model

    async def create(self, owner_id: str) -> ConversationResponse:
        async with async_session_scope(self._session_factory) as session:
            conversation = await ConversationRepository(session).create(owner_id)
            return ConversationResponse.model_validate(
                {**ConversationSummary.model_validate(conversation).model_dump(), "messages": []}
            )

    async def list(self, owner_id: str, *, limit: int, offset: int) -> ConversationListResponse:
        async with async_session_scope(self._session_factory) as session:
            rows = await ConversationRepository(session).list(owner_id, limit=limit, offset=offset)
            return ConversationListResponse(
                conversations=[ConversationSummary.model_validate(row) for row in rows],
                limit=limit,
                offset=offset,
            )

    async def get(self, owner_id: str, conversation_id: uuid.UUID) -> ConversationResponse:
        async with async_session_scope(self._session_factory) as session:
            snapshot = await ConversationRepository(session).get(owner_id, conversation_id)
            if snapshot is None:
                raise ConversationNotFound
            return self._response(snapshot.conversation, snapshot.messages)

    async def append_turn(
        self, owner_id: str, conversation_id: uuid.UUID, content: str
    ) -> AppendTurnResponse:
        async with async_session_scope(self._session_factory) as session:
            snapshot = await ConversationRepository(session).get(owner_id, conversation_id)
            if snapshot is None:
                raise ConversationNotFound
            if len(snapshot.messages) + 1 > 50:
                raise ConversationHistoryFull
            observed_version = snapshot.conversation.version
            history = tuple(
                ChatMessage(role=message.role, content=message.content)
                for message in snapshot.messages
            )

        model_response = await self._model.invoke(
            (*history, ChatMessage(role="user", content=content))
        )
        if (
            not isinstance(model_response, ModelResponse)
            or model_response.message.role != "assistant"
        ):
            raise InvalidModelOutput

        async with async_session_scope(self._session_factory) as session:
            await ConversationRepository(session).append_turn(
                owner_id=owner_id,
                conversation_id=conversation_id,
                observed_version=observed_version,
                user_content=content,
                assistant_content=model_response.message.content,
            )

        conversation = await self.get(owner_id, conversation_id)
        validated = ChatTurnResponse.model_validate(model_response.model_dump())
        return AppendTurnResponse(
            conversation=conversation, model=validated.model, usage=validated.usage
        )

    async def stream_turn(
        self, owner_id: str, conversation_id: uuid.UUID, content: str
    ) -> AsyncIterator[ConversationTextDelta | ConversationStreamCompleted]:
        async with async_session_scope(self._session_factory) as session:
            snapshot = await ConversationRepository(session).get(owner_id, conversation_id)
            if snapshot is None:
                raise ConversationNotFound
            if len(snapshot.messages) + 1 > 50:
                raise ConversationHistoryFull
            observed_version = snapshot.conversation.version
            history = tuple(
                ChatMessage(role=message.role, content=message.content)
                for message in snapshot.messages
            )

        text_parts: list[str] = []
        character_count = 0
        completed: ModelStreamCompleted | None = None
        async for event in self._model.stream(
            (*history, ChatMessage(role="user", content=content))
        ):
            if completed is not None:
                raise InvalidModelOutput
            if isinstance(event, AssistantTextDelta):
                if not event.text:
                    raise InvalidModelOutput
                character_count += len(event.text)
                if character_count > MAX_ASSISTANT_RESPONSE_CHARACTERS:
                    raise InvalidModelOutput
                text_parts.append(event.text)
                yield ConversationTextDelta(text=event.text)
            elif isinstance(event, ModelStreamCompleted):
                completed = event
            else:
                raise InvalidModelOutput
        assistant_content = "".join(text_parts)
        if (
            completed is None
            or completed.message.role != "assistant"
            or completed.message.content != assistant_content
            or not assistant_content.strip()
        ):
            raise InvalidModelOutput

        async with async_session_scope(self._session_factory) as session:
            await ConversationRepository(session).append_turn(
                owner_id=owner_id,
                conversation_id=conversation_id,
                observed_version=observed_version,
                user_content=content,
                assistant_content=assistant_content,
            )
        yield ConversationStreamCompleted(
            conversation=await self.get(owner_id, conversation_id),
            model=completed.model,
            usage=completed.usage,
        )

    @staticmethod
    def _response(conversation: object, messages: tuple[object, ...]) -> ConversationResponse:
        summary = ConversationSummary.model_validate(conversation)
        return ConversationResponse(
            **summary.model_dump(),
            messages=[
                ConversationMessageResponse.model_validate(message, from_attributes=True)
                for message in messages
            ],
        )


__all__ = [
    "AppendTurnRequest",
    "AppendTurnResponse",
    "ConversationHistoryFull",
    "ConversationListResponse",
    "ConversationNotFound",
    "ConversationResponse",
    "ConversationService",
    "ConversationStreamCompleted",
    "ConversationStreamError",
    "ConversationTextDelta",
    "StaleConversationError",
]
