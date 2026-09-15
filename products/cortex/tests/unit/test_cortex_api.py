import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from cortex_ai import (
    ChatMessage,
    ChatTurnService,
    InvalidModelOutput,
    ModelRejectedRequest,
    ModelResponse,
    ModelTimeout,
    ModelUnavailable,
    TokenUsage,
)
from cortex_api import create_app
from cortex_api.conversations import ConversationService, ConversationTextDelta
from cortex_api.settings import Settings
from cortex_brain import BrainClient


def brain_client(handler: httpx.MockTransport) -> BrainClient:
    return BrainClient(
        base_url="http://brain.test",
        api_key="secret",
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        http_client=httpx.AsyncClient(transport=handler, base_url="http://brain.test"),
    )


def test_health() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"service": "cortex-api", "status": "ok"}


def test_conversation_routes_require_one_safe_bearer_response() -> None:
    class UnusedService:
        async def create(self, _: str) -> object:
            raise AssertionError("unauthorized requests must not call the service")

    client = TestClient(create_app(conversation_service=cast(ConversationService, UnusedService())))

    for headers in ({}, {"Authorization": "Bearer wrong-secret"}):
        response = client.post("/conversations", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"error": "unauthorized"}
        assert "wrong-secret" not in response.text


def test_local_health_does_not_call_brain() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise AssertionError("Brain must not be called")

    response = TestClient(create_app(brain_client=brain_client(httpx.MockTransport(fail)))).get(
        "/health"
    )

    assert response.status_code == 200


def test_brain_diagnostic_checks_health_and_identity_without_exposing_identity() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(
                200, json={"status": "ok", "service": "brain-api", "environment": "test"}
            )
        return httpx.Response(
            200,
            json={
                "organization_id": "10000000-0000-0000-0000-000000000001",
                "principal_id": "20000000-0000-0000-0000-000000000001",
                "group_ids": [],
            },
        )

    response = TestClient(create_app(brain_client=brain_client(httpx.MockTransport(handler)))).get(
        "/health/brain"
    )

    assert response.status_code == 200
    assert response.json() == {"dependency": "brain", "status": "ok"}
    assert paths == ["/health", "/auth/context"]


@pytest.mark.parametrize(
    ("upstream_status", "diagnostic_status", "response_status"),
    [(401, "unauthorized", 502), (500, "error", 502)],
)
def test_brain_diagnostic_preserves_upstream_failure_kind(
    upstream_status: int, diagnostic_status: str, response_status: int
) -> None:
    response = TestClient(
        create_app(
            brain_client=brain_client(
                httpx.MockTransport(lambda _: httpx.Response(upstream_status, text="sensitive"))
            )
        )
    ).get("/health/brain")

    assert response.status_code == response_status
    assert response.json() == {"dependency": "brain", "status": diagnostic_status}


@pytest.mark.parametrize(
    ("response_factory", "diagnostic_status", "response_status"),
    [
        (lambda: httpx.Response(200, text="not-json"), "malformed", 502),
        (lambda: httpx.ConnectError("offline"), "unavailable", 503),
    ],
)
def test_brain_diagnostic_maps_malformed_and_unavailable(
    response_factory: Callable[[], httpx.Response | Exception],
    diagnostic_status: str,
    response_status: int,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        result = response_factory()
        if isinstance(result, Exception):
            raise result
        return result

    response = TestClient(create_app(brain_client=brain_client(httpx.MockTransport(handler)))).get(
        "/health/brain"
    )

    assert response.status_code == response_status
    assert response.json() == {"dependency": "brain", "status": diagnostic_status}


def test_brain_diagnostic_reports_disabled_integration() -> None:
    response = TestClient(create_app(settings=Settings())).get("/health/brain")

    assert response.status_code == 503
    assert response.json() == {"dependency": "brain", "status": "disabled"}


def test_partial_brain_configuration_is_invalid() -> None:
    with pytest.raises(ValueError, match="configured together"):
        Settings(brain_url="http://brain.test")


def test_model_settings_default_to_deterministic() -> None:
    settings = Settings()

    assert settings.model_backend == "deterministic"


@pytest.mark.parametrize(
    "values",
    [
        {"model_backend": "unknown"},
        {"model_backend": "openai"},
        {"model_backend": "openai", "openai_api_key": "secret"},
        {"model_backend": "openai", "openai_api_key": "   ", "openai_model": "gpt-test"},
        {"openai_timeout_seconds": 0.09},
        {"openai_timeout_seconds": 121},
    ],
)
def test_invalid_model_configuration_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Settings(**values)


def test_complete_openai_configuration_is_valid() -> None:
    settings = Settings(
        model_backend="openai",
        openai_api_key="synthetic-secret",
        openai_model="gpt-test",
        openai_timeout_seconds=5,
    )

    assert settings.openai_model == "gpt-test"


def test_owned_openai_model_is_injected_and_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        closed = False

        async def invoke(self, _: Sequence[ChatMessage]) -> ModelResponse:
            return ModelResponse(
                message=ChatMessage(role="assistant", content="fake answer"),
                model="fake-openai",
                usage=TokenUsage(input_tokens=1, output_tokens=2),
            )

        async def aclose(self) -> None:
            self.closed = True

    fake_model = FakeModel()
    creation_options: dict[str, object] = {}

    def create_fake_model(**options: object) -> FakeModel:
        creation_options.update(options)
        return fake_model

    monkeypatch.setattr("cortex_api.app.create_openai_chat_model", create_fake_model)
    app = create_app(
        settings=Settings(
            model_backend="openai", openai_api_key="synthetic-secret", openai_model="gpt-test"
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat/turn", json={"messages": [{"role": "user", "content": "hello"}]}
        )
        assert response.json()["model"] == "fake-openai"
        assert not fake_model.closed
    assert fake_model.closed
    assert creation_options == {
        "api_key": "synthetic-secret",
        "model": "gpt-test",
        "timeout_seconds": 30.0,
        "base_url": None,
        "organization": None,
        "project": None,
    }


def test_enabled_settings_construct_application_client() -> None:
    app = create_app(
        settings=Settings(brain_url="http://brain.test", brain_api_key="synthetic-secret")
    )

    with TestClient(app):
        assert isinstance(app.state.brain_client, BrainClient)


def test_chat_turn_uses_deterministic_model() -> None:
    response = TestClient(create_app()).post(
        "/chat/turn", json={"messages": [{"role": "user", "content": "Northstar hello"}]}
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": {"role": "assistant", "content": "Synthetic response to: Northstar hello"},
        "model": "cortex-deterministic-v1",
        "usage": {"input_tokens": 2, "output_tokens": 5},
    }


def test_streaming_turn_requires_authentication() -> None:
    response = TestClient(create_app()).post(
        "/conversations/10000000-0000-4000-8000-000000000001/turns/stream",
        json={"content": "hello"},
    )
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_streaming_turn_frames_safe_terminal_error_and_bounded_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingStreamService:
        async def stream_turn(
            self, owner_id: str, conversation_id: object, content: str
        ) -> AsyncIterator[ConversationTextDelta]:
            del owner_id, conversation_id, content
            yield ConversationTextDelta(text="synthetic delta")
            raise RuntimeError("provider-secret hidden reasoning submitted-content")

    caplog.set_level(logging.INFO, logger="cortex.stream")
    response = TestClient(
        create_app(conversation_service=cast(ConversationService, FailingStreamService()))
    ).post(
        "/conversations/10000000-0000-4000-8000-000000000001/turns/stream",
        headers={"Authorization": "Bearer cortex-local-dev"},
        json={"content": "submitted-content"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text == (
        'event: delta\ndata: {"text":"synthetic delta"}\n\n'
        'event: error\ndata: {"error":"conversation_error"}\n\n'
    )
    records = [record for record in caplog.records if record.name == "cortex.stream"]
    assert [vars(record)["stream_event"] for record in records] == [
        "start",
        "conversation_error",
    ]
    assert vars(records[-1])["emitted_characters"] == len("synthetic delta")
    assert vars(records[-1])["duration_ms"] >= 0
    rendered_logs = caplog.text
    for secret in ("provider-secret", "reasoning", "submitted-content", "cortex-local-dev"):
        assert secret not in rendered_logs


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ({"messages": []}, None),
        ({"messages": [{"role": "tool", "content": "x"}]}, None),
        ({"messages": [{"role": "user", "content": "  "}]}, None),
        ({"messages": [{"role": "user", "content": "x" * 8001}]}, None),
        (
            {"messages": [{"role": "assistant", "content": "synthetic"}]},
            "history_must_end_with_user",
        ),
    ],
)
def test_chat_turn_rejects_invalid_input(payload: object, expected_error: str | None) -> None:
    response = TestClient(create_app()).post("/chat/turn", json=payload)

    assert response.status_code == 422
    assert response.json() == {"error": expected_error or "invalid_request"}
    assert "x" * 8001 not in response.text


@pytest.mark.parametrize(
    ("failure", "response_status", "error"),
    [
        (ModelTimeout, 503, "model_timeout"),
        (ModelUnavailable, 503, "model_unavailable"),
        (InvalidModelOutput, 502, "invalid_model_response"),
        (ModelRejectedRequest, 502, "model_rejected_request"),
        (RuntimeError, 502, "model_error"),
    ],
)
def test_chat_turn_safely_translates_model_failures(
    failure: type[Exception], response_status: int, error: str
) -> None:
    class FailingModel:
        async def invoke(self, _: object) -> ModelResponse:
            raise failure("sensitive-secret hidden reasoning")

    response = TestClient(create_app(chat_service=ChatTurnService(FailingModel()))).post(
        "/chat/turn", json={"messages": [{"role": "user", "content": "hello"}]}
    )

    assert response.status_code == response_status
    assert response.json() == {"error": error}
    assert "sensitive-secret" not in response.text
    assert "reasoning" not in response.text
