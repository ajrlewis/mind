from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar, cast
from uuid import uuid4

import pytest

from cortex_ai import (
    MAX_ASSISTANT_RESPONSE_CHARACTERS,
    AssistantTextDelta,
    ChatMessage,
    DeterministicChatModel,
    InvalidModelOutput,
    ModelStreamCompleted,
)
from cortex_api import conversations
from cortex_api.conversations import (
    ConversationHistoryFull,
    ConversationNotFound,
    ConversationService,
)
from cortex_state import AsyncSessionFactory, ConversationSnapshot


class FakeSession:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


class FakeRepository:
    conversation = SimpleNamespace(
        id=uuid4(),
        title=None,
        owner_id="owner-a",
        version=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    messages: ClassVar[list[SimpleNamespace]] = []

    def __init__(self, _: object) -> None:
        pass

    async def create(self, owner_id: str) -> object:
        self.conversation.owner_id = owner_id
        return self.conversation

    async def list(self, owner_id: str, *, limit: int, offset: int) -> tuple[object, ...]:
        del limit, offset
        return (self.conversation,) if owner_id == self.conversation.owner_id else ()

    async def get(self, owner_id: str, conversation_id: object) -> ConversationSnapshot | None:
        if owner_id != self.conversation.owner_id or conversation_id != self.conversation.id:
            return None
        return ConversationSnapshot(self.conversation, tuple(self.messages))

    async def append_turn(self, *, user_content: str, assistant_content: str, **_: object) -> None:
        now = datetime.now(UTC)
        for role, content in (("user", user_content), ("assistant", assistant_content)):
            self.messages.append(
                SimpleNamespace(
                    id=uuid4(),
                    sequence=len(self.messages) + 1,
                    role=role,
                    content=content,
                    created_at=now,
                )
            )
        self.conversation.version += 2


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> ConversationService:
    FakeRepository.messages = []
    FakeRepository.conversation.version = 0
    monkeypatch.setattr(conversations, "ConversationRepository", FakeRepository)
    return ConversationService(
        cast(AsyncSessionFactory, lambda: FakeSession()), DeterministicChatModel()
    )


async def test_service_create_list_reopen_and_append(service: ConversationService) -> None:
    created = await service.create("owner-a")
    assert created.messages == []
    assert (await service.list("owner-a", limit=10, offset=0)).conversations[0].id == created.id
    turn = await service.append_turn("owner-a", created.id, "hello world")
    assert [message.role for message in turn.conversation.messages] == ["user", "assistant"]
    assert turn.model == "cortex-deterministic-v1"
    assert [message.role for message in (await service.get("owner-a", created.id)).messages] == [
        "user",
        "assistant",
    ]

    events = [event async for event in service.stream_turn("owner-a", created.id, "stream me")]
    assert len(events) == 3
    assert events[-1].conversation.messages[-1].content == "Synthetic response to: stream me"


async def test_service_hides_missing_and_bounds_history(service: ConversationService) -> None:
    with pytest.raises(ConversationNotFound):
        await service.get("other-owner", FakeRepository.conversation.id)
    FakeRepository.messages = [
        SimpleNamespace(
            id=uuid4(),
            sequence=index + 1,
            role="user" if index % 2 == 0 else "assistant",
            content="x",
            created_at=datetime.now(UTC),
        )
        for index in range(50)
    ]
    with pytest.raises(ConversationHistoryFull):
        await service.append_turn("owner-a", FakeRepository.conversation.id, "too much")


async def test_cancelled_stream_does_not_publish_partial_turn(service: ConversationService) -> None:
    stream = service.stream_turn("owner-a", FakeRepository.conversation.id, "cancel me")
    await anext(stream)
    await stream.aclose()
    assert FakeRepository.messages == []


@pytest.mark.parametrize(
    "events",
    [
        [AssistantTextDelta(text="partial")],
        [
            AssistantTextDelta(text="partial"),
            ModelStreamCompleted(
                message=ChatMessage(role="assistant", content="different"), model="synthetic"
            ),
        ],
        [
            AssistantTextDelta(text="partial"),
            ModelStreamCompleted(
                message=ChatMessage(role="user", content="partial"), model="synthetic"
            ),
        ],
        [
            AssistantTextDelta(text="partial"),
            ModelStreamCompleted(
                message=ChatMessage(role="assistant", content="partial"), model="synthetic"
            ),
            AssistantTextDelta(text="after terminal"),
        ],
    ],
)
async def test_stream_rejects_malformed_terminal_contract_without_publication(
    service: ConversationService, events: list[object]
) -> None:
    class MalformedModel:
        async def stream(self, _: Sequence[ChatMessage]) -> AsyncIterator[object]:
            for event in events:
                yield event

    service._model = MalformedModel()  # type: ignore[assignment]
    with pytest.raises(InvalidModelOutput):
        _ = [
            event
            async for event in service.stream_turn(
                "owner-a", FakeRepository.conversation.id, "malformed"
            )
        ]
    assert FakeRepository.messages == []


async def test_stream_rejects_empty_delta_without_publication(
    service: ConversationService,
) -> None:
    class InvalidDeltaModel:
        async def stream(self, _: Sequence[ChatMessage]) -> AsyncIterator[AssistantTextDelta]:
            yield AssistantTextDelta.model_construct(text="")
            yield AssistantTextDelta(text="x" * (MAX_ASSISTANT_RESPONSE_CHARACTERS + 1))

    service._model = InvalidDeltaModel()  # type: ignore[assignment]
    with pytest.raises(InvalidModelOutput):
        _ = [
            event
            async for event in service.stream_turn("owner-a", FakeRepository.conversation.id, "bad")
        ]
    assert FakeRepository.messages == []
