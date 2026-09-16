import asyncio
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.responses import Response

from cortex_ai import (
    ChatMessage,
    InvalidModelOutput,
    ModelRejectedRequest,
    ModelTimeout,
    ModelUnavailable,
    OpenAIChatModel,
    create_openai_chat_model,
)


def response(*, content: list[dict[str, Any]] | None = None, usage: object = "default") -> Response:
    data: dict[str, Any] = {
        "id": "resp_synthetic",
        "created_at": 1,
        "object": "response",
        "status": "completed",
        "model": "gpt-synthetic-2026-01-01",
        "output": [
            {
                "id": "msg_synthetic",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content
                if content is not None
                else [{"type": "output_text", "text": "Synthetic answer", "annotations": []}],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
    }
    data["usage"] = (
        {
            "input_tokens": 7,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens": 3,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 10,
        }
        if usage == "default"
        else usage
    )
    return Response.model_validate(data)


class FakeResponses:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeClient:
    def __init__(self, result: object) -> None:
        self.responses = FakeResponses(result)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def model(result: object) -> tuple[OpenAIChatModel, FakeClient]:
    client = FakeClient(result)
    return OpenAIChatModel(client=cast(AsyncOpenAI, client), model="gpt-synthetic"), client


async def test_maps_ordered_messages_once_and_returns_identity_and_usage() -> None:
    adapter, client = model(response())
    messages = [
        ChatMessage(role="system", content="System context"),
        ChatMessage(role="assistant", content="Earlier answer"),
        ChatMessage(role="user", content="Question"),
    ]

    result = await adapter.invoke(messages)

    assert client.responses.calls == [
        {
            "model": "gpt-synthetic",
            "input": [
                {"role": "system", "content": "System context"},
                {"role": "assistant", "content": "Earlier answer"},
                {"role": "user", "content": "Question"},
            ],
            "store": False,
        }
    ]
    assert result.message == ChatMessage(role="assistant", content="Synthetic answer")
    assert result.model == "gpt-synthetic-2026-01-01"
    assert result.usage is not None
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 3


async def test_usage_is_optional() -> None:
    adapter, _ = model(response(usage=None))

    assert (await adapter.invoke([ChatMessage(role="user", content="Question")])).usage is None


async def test_injected_client_remains_caller_owned() -> None:
    adapter, client = model(response())

    await adapter.aclose()

    assert not client.closed


async def test_factory_configures_bounded_no_retry_owned_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(response())
    options: dict[str, object] = {}

    def create_client(**kwargs: object) -> AsyncOpenAI:
        options.update(kwargs)
        return cast(AsyncOpenAI, client)

    monkeypatch.setattr("cortex_ai.openai.AsyncOpenAI", create_client)
    adapter = create_openai_chat_model(
        api_key="synthetic-secret",
        model="gpt-synthetic",
        timeout_seconds=4.5,
        base_url="https://api.openai.test/v1",
        organization="org_synthetic",
        project="proj_synthetic",
    )

    await adapter.aclose()

    assert options == {
        "api_key": "synthetic-secret",
        "base_url": "https://api.openai.test/v1",
        "organization": "org_synthetic",
        "project": "proj_synthetic",
        "timeout": 4.5,
        "max_retries": 0,
    }
    assert client.closed


def status_response(status_code: int = 400) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.test/v1/responses")
    return httpx.Response(status_code, request=request, text="provider-secret")


@pytest.mark.parametrize(
    "provider_error",
    [
        AuthenticationError(
            "provider-secret", response=status_response(401), body="provider-secret"
        ),
        PermissionDeniedError(
            "provider-secret", response=status_response(403), body="provider-secret"
        ),
        BadRequestError("provider-secret", response=status_response(), body="provider-secret"),
        ConflictError("provider-secret", response=status_response(409), body="provider-secret"),
    ],
)
async def test_rejection_errors_are_safe(provider_error: Exception) -> None:
    adapter, _ = model(provider_error)

    with pytest.raises(ModelRejectedRequest) as caught:
        await adapter.invoke([ChatMessage(role="user", content="secret prompt")])

    assert str(caught.value) == ""


@pytest.mark.parametrize(
    ("provider_error", "expected"),
    [
        (
            RateLimitError(
                "provider-secret", response=status_response(429), body="provider-secret"
            ),
            ModelUnavailable,
        ),
        (
            APIConnectionError(request=httpx.Request("POST", "https://api.openai.test")),
            ModelUnavailable,
        ),
        (APITimeoutError(httpx.Request("POST", "https://api.openai.test")), ModelTimeout),
        (RuntimeError("provider-secret"), ModelUnavailable),
    ],
)
async def test_transient_and_unexpected_errors_are_safe(
    provider_error: Exception, expected: type[Exception]
) -> None:
    adapter, _ = model(provider_error)

    with pytest.raises(expected) as caught:
        await adapter.invoke([ChatMessage(role="user", content="secret prompt")])

    assert str(caught.value) == ""


async def test_sdk_response_validation_error_is_invalid_output() -> None:
    adapter, _ = model(
        APIResponseValidationError(
            status_response(200), "provider-secret", message="provider-secret"
        )
    )

    with pytest.raises(InvalidModelOutput) as caught:
        await adapter.invoke([ChatMessage(role="user", content="secret prompt")])

    assert str(caught.value) == ""


@pytest.mark.parametrize(
    "provider_response",
    [
        response().model_copy(update={"output": []}),
        response().model_copy(update={"status": "incomplete"}),
        response(content=[]),
        response(content=[{"type": "refusal", "refusal": "provider-secret"}]),
        response(
            content=[
                {"type": "output_text", "text": "one", "annotations": []},
                {"type": "output_text", "text": "two", "annotations": []},
            ]
        ),
        response(content=[{"type": "output_text", "text": "   ", "annotations": []}]),
        response(
            usage={
                "input_tokens": -1,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens": 1,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 0,
            }
        ),
    ],
)
async def test_malformed_outputs_are_rejected_without_details(provider_response: Response) -> None:
    adapter, _ = model(provider_response)

    with pytest.raises(InvalidModelOutput) as caught:
        await adapter.invoke([ChatMessage(role="user", content="Question")])

    assert str(caught.value) == ""


class FakeStream:
    def __init__(self, events: list[object], failure: Exception | None = None) -> None:
        self.events = events
        self.failure = failure
        self.closed = False
        self.waiting: asyncio.Event | None = None

    def __aiter__(self) -> "FakeStream":
        return self

    async def __anext__(self) -> object:
        if self.events:
            return self.events.pop(0)
        if self.waiting is not None:
            await self.waiting.wait()
        if self.failure is not None:
            raise self.failure
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


def delta(text: str) -> object:
    return SimpleNamespace(type="response.output_text.delta", delta=text)


def completed(result: Response | None = None) -> object:
    return SimpleNamespace(type="response.completed", response=result or response())


async def test_stream_yields_ordered_deltas_and_matching_terminal_then_closes() -> None:
    stream = FakeStream([delta("Synthetic "), delta("answer"), completed()])
    adapter, client = model(stream)

    events = [
        event async for event in adapter.stream([ChatMessage(role="user", content="Question")])
    ]

    assert [event.text for event in events[:2]] == ["Synthetic ", "answer"]
    assert events[2].message == ChatMessage(role="assistant", content="Synthetic answer")
    assert stream.closed
    assert client.responses.calls[0]["stream"] is True
    assert client.responses.calls[0]["store"] is False


@pytest.mark.parametrize(
    "events",
    [
        [delta("Synthetic answer")],
        [delta("Synthetic answer"), completed(), completed()],
        [delta("Synthetic answer"), completed(), delta("extra")],
        [delta("Synthetic answer"), completed(response().model_copy(update={"output": []}))],
        [
            delta("Synthetic answer"),
            completed(
                response().model_copy(
                    update={
                        "output": [
                            SimpleNamespace(
                                type="message",
                                role="user",
                                content=[
                                    SimpleNamespace(type="output_text", text="Synthetic answer")
                                ],
                            )
                        ]
                    }
                )
            ),
        ],
        [delta("different"), completed()],
        [delta("")],
        [SimpleNamespace(type="response.failed", response="provider-secret")],
    ],
)
async def test_stream_rejects_malformed_output_and_closes(events: list[object]) -> None:
    stream = FakeStream(events)
    adapter, _ = model(stream)

    with pytest.raises(InvalidModelOutput) as caught:
        _ = [
            event
            async for event in adapter.stream([ChatMessage(role="user", content="secret prompt")])
        ]

    assert str(caught.value) == ""
    assert stream.closed


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (APITimeoutError(httpx.Request("POST", "https://api.openai.test")), ModelTimeout),
        (RuntimeError("provider-secret"), ModelUnavailable),
        (
            BadRequestError("provider-secret", response=status_response(), body="provider-secret"),
            ModelRejectedRequest,
        ),
    ],
)
async def test_stream_maps_provider_failure_safely_and_closes(
    failure: Exception, expected: type[Exception]
) -> None:
    stream = FakeStream([delta("partial")], failure)
    adapter, _ = model(stream)

    with pytest.raises(expected) as caught:
        _ = [
            event
            async for event in adapter.stream([ChatMessage(role="user", content="secret prompt")])
        ]

    assert str(caught.value) == ""
    assert stream.closed


async def test_stream_cancellation_closes_provider_stream() -> None:
    stream = FakeStream([delta("partial")])
    stream.waiting = asyncio.Event()
    adapter, _ = model(stream)

    async def consume() -> None:
        _ = [
            event async for event in adapter.stream([ChatMessage(role="user", content="Question")])
        ]

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
