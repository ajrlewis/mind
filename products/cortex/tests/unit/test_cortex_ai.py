import asyncio
from collections.abc import Sequence
from typing import cast

import pytest
from pydantic import ValidationError

from cortex_ai import (
    MAX_MESSAGE_CHARACTERS,
    ChatMessage,
    ChatModel,
    ChatTurnRequest,
    ChatTurnService,
    DeterministicChatModel,
    InvalidChatHistory,
    InvalidModelOutput,
    ModelRejectedRequest,
    ModelResponse,
    ModelTimeout,
    ModelUnavailable,
    TokenUsage,
)


async def test_deterministic_stream_emits_ordered_deltas_and_terminal_metadata() -> None:
    events = [
        event
        async for event in DeterministicChatModel().stream(
            [ChatMessage(role="user", content="hello stream")]
        )
    ]
    assert len(events) == 3
    assert "".join(event.text for event in events[:-1]) == "Synthetic response to: hello stream"
    assert events[-1].model == "cortex-deterministic-v1"


async def test_deterministic_stream_delay_is_cancellable_after_first_delta() -> None:
    stream = DeterministicChatModel(stream_delay_seconds=5).stream(
        [ChatMessage(role="user", content="cancel stream")]
    )

    assert (await anext(stream)).text
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending
    await stream.aclose()


class RecordingModel:
    def __init__(self) -> None:
        self.calls: list[Sequence[ChatMessage]] = []

    async def invoke(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        self.calls.append(messages)
        return ModelResponse(
            message=ChatMessage(role="assistant", content="synthetic answer"),
            model="test-model",
            usage=TokenUsage(input_tokens=2, output_tokens=2),
        )


async def test_turn_preserves_order_and_invokes_model_once() -> None:
    model = RecordingModel()
    service = ChatTurnService(model)
    messages = [
        ChatMessage(role="system", content="Synthetic system context"),
        ChatMessage(role="assistant", content="Earlier synthetic answer"),
        ChatMessage(role="user", content="Synthetic question"),
    ]

    result = await service.turn(ChatTurnRequest(messages=messages))

    assert len(model.calls) == 1
    assert list(model.calls[0]) == messages
    assert result.message.content == "synthetic answer"
    assert result.model == "test-model"


async def test_deterministic_model_output_remains_bounded() -> None:
    request = ChatTurnRequest(
        messages=[ChatMessage(role="user", content="x" * MAX_MESSAGE_CHARACTERS)]
    )

    result = await ChatTurnService(DeterministicChatModel()).turn(request)

    assert len(result.message.content) == MAX_MESSAGE_CHARACTERS


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [ChatMessage(role="user", content="x")] * 51,
    ],
)
def test_history_length_is_bounded(messages: list[ChatMessage]) -> None:
    with pytest.raises(ValidationError):
        ChatTurnRequest(messages=messages)


@pytest.mark.parametrize("content", ["", "   ", "x" * (MAX_MESSAGE_CHARACTERS + 1)])
def test_message_content_is_nonblank_and_bounded(content: str) -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content=content)


def test_message_role_is_closed() -> None:
    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"role": "tool", "content": "synthetic"})


async def test_history_must_end_with_user() -> None:
    service = ChatTurnService(RecordingModel())

    with pytest.raises(InvalidChatHistory):
        await service.turn(
            ChatTurnRequest(messages=[ChatMessage(role="assistant", content="synthetic")])
        )


class ResultModel:
    def __init__(self, result: object) -> None:
        self.result = result

    async def invoke(self, _: Sequence[ChatMessage]) -> ModelResponse:
        return cast(ModelResponse, self.result)


async def test_invalid_model_object_is_rejected() -> None:
    service = ChatTurnService(cast(ChatModel, ResultModel({"secret": "not exposed"})))

    with pytest.raises(InvalidModelOutput):
        await service.turn(ChatTurnRequest(messages=[ChatMessage(role="user", content="hello")]))


async def test_non_assistant_model_output_is_rejected() -> None:
    response = ModelResponse(
        message=ChatMessage(role="user", content="invalid output"), model="test-model"
    )

    with pytest.raises(InvalidModelOutput):
        await ChatTurnService(ResultModel(response)).turn(
            ChatTurnRequest(messages=[ChatMessage(role="user", content="hello")])
        )


@pytest.mark.parametrize(
    "error_type", [ModelRejectedRequest, ModelTimeout, ModelUnavailable, RuntimeError]
)
async def test_model_failures_remain_distinct(error_type: type[Exception]) -> None:
    class FailingModel:
        async def invoke(self, _: Sequence[ChatMessage]) -> ModelResponse:
            raise error_type("sensitive provider detail")

    with pytest.raises(error_type):
        await ChatTurnService(FailingModel()).turn(
            ChatTurnRequest(messages=[ChatMessage(role="user", content="hello")])
        )
