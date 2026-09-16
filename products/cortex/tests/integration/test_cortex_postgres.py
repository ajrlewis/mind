import asyncio
import logging
import os
from collections.abc import AsyncIterator, Sequence

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select, update

from cortex_ai import (
    MAX_ASSISTANT_RESPONSE_CHARACTERS,
    AssistantTextDelta,
    ChatMessage,
    InvalidModelOutput,
    ModelResponse,
    ModelStreamCompleted,
)
from cortex_api.conversations import ConversationNotFound, ConversationService
from cortex_api.settings import Settings
from cortex_state import (
    Conversation,
    ConversationMessage,
    StaleConversationError,
    create_async_engine,
    create_async_session_factory,
)


def integration_settings(database_url: str) -> Settings:
    return Settings(
        cortex_database_url=database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    )


class RecordingModel:
    def __init__(self) -> None:
        self.calls: list[tuple[ChatMessage, ...]] = []

    async def invoke(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        self.calls.append(tuple(messages))
        return ModelResponse(
            message=ChatMessage(role="assistant", content="synthetic answer"), model="test-model"
        )


@pytest.fixture
def cortex_database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    database_url = os.getenv("CORTEX_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("CORTEX_TEST_DATABASE_URL is required for Cortex PostgreSQL tests")
    sqlalchemy_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    monkeypatch.setenv("CORTEX_DATABASE_URL", sqlalchemy_url)
    config = Config("products/cortex/alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return database_url


@pytest.mark.integration
def test_clean_cortex_migration_is_separate_and_constrained(cortex_database_url: str) -> None:
    with (
        psycopg.connect(cortex_database_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone() == ("20260915_0001",)
        cursor.execute("SELECT to_regclass('organizations'), to_regclass('conversations')")
        assert cursor.fetchone() == (None, "conversations")
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO conversations (id, owner_id) VALUES (gen_random_uuid(), '')"
            )


@pytest.mark.integration
def test_cortex_migration_preserves_existing_loggers(cortex_database_url: str) -> None:
    logger = logging.getLogger("cortex.stream")
    logger.disabled = False
    config = Config("products/cortex/alembic.ini")

    command.upgrade(config, "head")

    assert logger.disabled is False


@pytest.mark.integration
async def test_conversation_flow_is_ordered_owned_and_atomic(cortex_database_url: str) -> None:
    settings = integration_settings(cortex_database_url)
    engine = create_async_engine(settings)
    factory = create_async_session_factory(engine)
    model = RecordingModel()
    service = ConversationService(factory, model)
    try:
        created = await service.create("owner-a")
        assert created.messages == []
        assert [
            item.id for item in (await service.list("owner-a", limit=20, offset=0)).conversations
        ] == [created.id]
        assert (await service.list("owner-b", limit=20, offset=0)).conversations == []
        with pytest.raises(ConversationNotFound):
            await service.get("owner-b", created.id)

        result = await service.append_turn("owner-a", created.id, "hello")
        assert [
            (message.sequence, message.role, message.content)
            for message in result.conversation.messages
        ] == [(1, "user", "hello"), (2, "assistant", "synthetic answer")]
        assert len(model.calls) == 1
        assert [(message.role, message.content) for message in model.calls[0]] == [
            ("user", "hello")
        ]
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_model_failure_and_stale_writer_publish_nothing(cortex_database_url: str) -> None:
    settings = integration_settings(cortex_database_url)
    engine = create_async_engine(settings)
    factory = create_async_session_factory(engine)

    class FailingModel:
        async def invoke(self, _: Sequence[ChatMessage]) -> ModelResponse:
            raise RuntimeError("sensitive provider failure")

    failing_service = ConversationService(factory, FailingModel())
    created = await failing_service.create("owner-a")
    with pytest.raises(RuntimeError):
        await failing_service.append_turn("owner-a", created.id, "not persisted")
    assert (await failing_service.get("owner-a", created.id)).messages == []

    model = RecordingModel()
    service = ConversationService(factory, model)
    original_invoke = model.invoke
    ready = asyncio.Event()
    release = asyncio.Event()

    async def delayed(messages: Sequence[ChatMessage]) -> ModelResponse:
        ready.set()
        await release.wait()
        return await original_invoke(messages)

    model.invoke = delayed  # type: ignore[method-assign]
    stale_task = asyncio.create_task(service.append_turn("owner-a", created.id, "stale"))
    await ready.wait()
    await ConversationService(factory, RecordingModel()).append_turn(
        "owner-a", created.id, "winner"
    )
    release.set()
    with pytest.raises(StaleConversationError):
        await stale_task
    reopened = await service.get("owner-a", created.id)
    assert [message.content for message in reopened.messages] == ["winner", "synthetic answer"]

    async with factory() as session:
        assert len(tuple((await session.scalars(select(ConversationMessage))).all())) == 2
        conversation = await session.scalar(select(Conversation))
        assert conversation is not None and conversation.version == 2
    await engine.dispose()


@pytest.mark.integration
async def test_stream_cancellation_after_delta_keeps_postgres_unchanged(
    cortex_database_url: str,
) -> None:
    settings = integration_settings(cortex_database_url)
    engine = create_async_engine(settings)
    factory = create_async_session_factory(engine)
    release = asyncio.Event()

    class SlowModel:
        async def stream(
            self, _: Sequence[ChatMessage]
        ) -> AsyncIterator[AssistantTextDelta | ModelStreamCompleted]:
            yield AssistantTextDelta(text="partial")
            await release.wait()
            yield ModelStreamCompleted(
                message=ChatMessage(role="assistant", content="partial complete"),
                model="slow-synthetic",
            )

    service = ConversationService(factory, SlowModel())
    try:
        created = await service.create("stream-owner")
        stream = service.stream_turn("stream-owner", created.id, "cancel this")
        assert (await anext(stream)).text == "partial"
        assert engine.pool.checkedout() == 0
        await stream.aclose()
        assert (await service.get("stream-owner", created.id)).messages == []
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["provider", "malformed", "overflow"])
async def test_failed_streams_publish_no_partial_turn(
    cortex_database_url: str, failure: str
) -> None:
    settings = integration_settings(cortex_database_url)
    engine = create_async_engine(settings)
    factory = create_async_session_factory(engine)

    class FailingStreamModel:
        async def stream(
            self, _: Sequence[ChatMessage]
        ) -> AsyncIterator[AssistantTextDelta | ModelStreamCompleted]:
            yield AssistantTextDelta(text="partial")
            if failure == "provider":
                raise RuntimeError("synthetic provider body")
            if failure == "overflow":
                yield AssistantTextDelta(text="x" * MAX_ASSISTANT_RESPONSE_CHARACTERS)
                return
            yield ModelStreamCompleted(
                message=ChatMessage(role="assistant", content="mismatch"),
                model="synthetic",
            )

    service = ConversationService(factory, FailingStreamModel())
    try:
        created = await service.create(f"{failure}-owner")
        expected = RuntimeError if failure == "provider" else InvalidModelOutput
        with pytest.raises(expected):
            _ = [
                event
                async for event in service.stream_turn(
                    f"{failure}-owner", created.id, "must stay atomic"
                )
            ]
        assert (await service.get(f"{failure}-owner", created.id)).messages == []
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_successful_stream_publishes_one_canonical_pair(cortex_database_url: str) -> None:
    engine = create_async_engine(integration_settings(cortex_database_url))
    factory = create_async_session_factory(engine)

    class Model:
        async def stream(
            self, _: Sequence[ChatMessage]
        ) -> AsyncIterator[AssistantTextDelta | ModelStreamCompleted]:
            yield AssistantTextDelta(text="synthetic ")
            yield AssistantTextDelta(text="answer")
            yield ModelStreamCompleted(
                message=ChatMessage(role="assistant", content="synthetic answer"),
                model="synthetic",
            )

    service = ConversationService(factory, Model())
    try:
        created = await service.create("stream-owner")
        events = [
            item async for item in service.stream_turn("stream-owner", created.id, "question")
        ]
        assert [item.text for item in events[:2]] == ["synthetic ", "answer"]
        assert [
            (item.sequence, item.role, item.content) for item in events[2].conversation.messages
        ] == [(1, "user", "question"), (2, "assistant", "synthetic answer")]
        reopened = await service.get("stream-owner", created.id)
        assert reopened.messages == events[2].conversation.messages
        async with factory() as session:
            assert len(tuple((await session.scalars(select(ConversationMessage))).all())) == 2
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_stream_wait_releases_connection_and_stale_writer_publishes_nothing(
    cortex_database_url: str,
) -> None:
    engine = create_async_engine(integration_settings(cortex_database_url))
    factory = create_async_session_factory(engine)
    waiting = asyncio.Event()
    release = asyncio.Event()

    class PausedModel:
        async def stream(
            self, _: Sequence[ChatMessage]
        ) -> AsyncIterator[AssistantTextDelta | ModelStreamCompleted]:
            yield AssistantTextDelta(text="loser")
            waiting.set()
            await release.wait()
            yield ModelStreamCompleted(
                message=ChatMessage(role="assistant", content="loser"), model="synthetic"
            )

    service = ConversationService(factory, PausedModel())
    try:
        created = await service.create("stream-owner")
        stream = service.stream_turn("stream-owner", created.id, "losing user")
        assert (await anext(stream)).text == "loser"
        task = asyncio.create_task(anext(stream))
        await asyncio.wait_for(waiting.wait(), 1)
        assert engine.pool.checkedout() == 0
        with (
            psycopg.connect(cortex_database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() AND state = 'idle in transaction'"
            )
            assert cursor.fetchone() == (0,)
        await ConversationService(factory, RecordingModel()).append_turn(
            "stream-owner", created.id, "winner"
        )
        release.set()
        with pytest.raises(StaleConversationError):
            await task
        await stream.aclose()
        reopened = await service.get("stream-owner", created.id)
        assert [item.content for item in reopened.messages] == ["winner", "synthetic answer"]
    finally:
        release.set()
        await engine.dispose()


@pytest.mark.integration
async def test_stream_history_full_and_commit_failure_publish_nothing(
    cortex_database_url: str,
) -> None:
    engine = create_async_engine(integration_settings(cortex_database_url))
    factory = create_async_session_factory(engine)

    class Model:
        calls = 0

        async def stream(
            self, _: Sequence[ChatMessage]
        ) -> AsyncIterator[AssistantTextDelta | ModelStreamCompleted]:
            self.calls += 1
            yield AssistantTextDelta(text="answer")
            yield ModelStreamCompleted(
                message=ChatMessage(role="assistant", content="answer"), model="synthetic"
            )

    model = Model()
    service = ConversationService(factory, model)
    try:
        full = await service.create("full-owner")
        async with factory.begin() as session:
            session.add_all(
                ConversationMessage(
                    conversation_id=full.id,
                    sequence=index,
                    role="user" if index % 2 else "assistant",
                    content="synthetic",
                )
                for index in range(1, 51)
            )
            await session.execute(
                update(Conversation).where(Conversation.id == full.id).values(version=50)
            )
        from cortex_api.conversations import ConversationHistoryFull

        with pytest.raises(ConversationHistoryFull):
            _ = [item async for item in service.stream_turn("full-owner", full.id, "new")]
        assert model.calls == 0
        assert len((await service.get("full-owner", full.id)).messages) == 50

        failed = await service.create("failed-owner")

        commits = 0

        def fail_commit(_: object) -> None:
            nonlocal commits
            commits += 1
            if commits == 2:
                raise RuntimeError("synthetic commit failure")

        event.listen(engine.sync_engine, "commit", fail_commit)
        try:
            with pytest.raises(RuntimeError, match="synthetic commit failure"):
                _ = [item async for item in service.stream_turn("failed-owner", failed.id, "new")]
        finally:
            event.remove(engine.sync_engine, "commit", fail_commit)
        assert (await service.get("failed-owner", failed.id)).messages == []
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()
