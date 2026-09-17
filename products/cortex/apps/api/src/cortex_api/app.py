import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Literal, Protocol, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from cortex_ai import (
    ChatModel,
    ChatTurnRequest,
    ChatTurnResponse,
    ChatTurnService,
    DeterministicChatModel,
    InvalidChatHistory,
    InvalidModelOutput,
    ModelRejectedRequest,
    ModelTimeout,
    ModelUnavailable,
    create_openai_chat_model,
)
from cortex_api.conversations import (
    AppendTurnRequest,
    AppendTurnResponse,
    ConversationHistoryFull,
    ConversationListResponse,
    ConversationNotFound,
    ConversationResponse,
    ConversationService,
    ConversationStreamCompleted,
    ConversationStreamError,
    ConversationTextDelta,
    StaleConversationError,
)
from cortex_api.knowledge import (
    AnswerResponse,
    KnowledgeAnswerService,
    KnowledgeChanged,
    KnowledgeLookupService,
    LookupRequest,
    LookupResponse,
)
from cortex_api.settings import Settings, get_settings
from cortex_auth import AuthenticationError, CallerIdentity, LocalBearerAuthenticator
from cortex_brain import (
    BrainClient,
    BrainMalformedResponse,
    BrainRejectedCredentials,
    BrainUnavailable,
    BrainUnexpectedResponse,
)
from cortex_state import create_async_engine, create_async_session_factory

logger = logging.getLogger("cortex.stream")


def _sse(event: str, payload: BaseModel) -> str:
    """Serialize the documented two-line SSE envelope around authoritative schemas."""
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


class AsyncCloseable(Protocol):
    async def aclose(self) -> None: ...


class HealthResponse(BaseModel):
    service: Literal["cortex-api"]
    status: Literal["ok"]


class BrainDiagnosticResponse(BaseModel):
    dependency: Literal["brain"] = "brain"
    status: Literal["ok", "disabled", "unauthorized", "malformed", "unavailable", "error"]


def _create_brain_client(settings: Settings) -> BrainClient | None:
    if settings.brain_url is None or settings.brain_api_key is None:
        return None
    return BrainClient(
        base_url=str(settings.brain_url),
        api_key=settings.brain_api_key.get_secret_value(),
        connect_timeout_seconds=settings.brain_connect_timeout_seconds,
        read_timeout_seconds=settings.brain_read_timeout_seconds,
    )


def _create_chat_model(settings: Settings) -> tuple[ChatModel, AsyncCloseable | None]:
    if settings.model_backend == "deterministic":
        return DeterministicChatModel(
            stream_delay_seconds=settings.deterministic_stream_delay_seconds
        ), None
    assert settings.openai_api_key is not None
    assert settings.openai_model is not None
    model = create_openai_chat_model(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        base_url=str(settings.openai_base_url) if settings.openai_base_url is not None else None,
        organization=settings.openai_organization,
        project=settings.openai_project,
    )
    return model, model


def create_app(
    *,
    settings: Settings | None = None,
    brain_client: BrainClient | None = None,
    chat_service: ChatTurnService | None = None,
    conversation_service: ConversationService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_client = brain_client or _create_brain_client(resolved_settings)
    owned_model: AsyncCloseable | None = None
    if chat_service is None:
        model, owned_model = _create_chat_model(resolved_settings)
        resolved_chat_service = ChatTurnService(model)
    else:
        resolved_chat_service = chat_service
    authenticator = LocalBearerAuthenticator(
        token=resolved_settings.cortex_local_bearer_token,
        owner_id=resolved_settings.cortex_local_owner_id,
    )
    owned_engine = None
    if conversation_service is None:
        owned_engine = create_async_engine(resolved_settings)
        session_factory = create_async_session_factory(owned_engine)
        if chat_service is None:
            conversation_model = model
        else:
            conversation_model, additional_owned_model = _create_chat_model(resolved_settings)
            if additional_owned_model is not None:
                owned_model = additional_owned_model
        resolved_conversation_service = ConversationService(session_factory, conversation_model)
    else:
        resolved_conversation_service = conversation_service

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        if resolved_client is not None:
            await resolved_client.aclose()
        if owned_model is not None:
            await owned_model.aclose()
        if owned_engine is not None:
            await owned_engine.dispose()

    app = FastAPI(title="Cortex", version="0.1.0", lifespan=lifespan)
    app.state.brain_client = resolved_client
    app.state.chat_service = resolved_chat_service
    app.state.conversation_service = resolved_conversation_service
    lookup_service = (
        KnowledgeLookupService(resolved_client) if resolved_client is not None else None
    )
    answer_service = (
        KnowledgeAnswerService(resolved_client, resolved_chat_service)
        if resolved_client is not None
        else None
    )

    def caller(authorization: Annotated[str | None, Header()] = None) -> CallerIdentity:
        try:
            return authenticator.authenticate(authorization)
        except AuthenticationError:
            raise HTTPException(status_code=401, detail="unauthorized") from None

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "invalid_request"})

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exception: HTTPException) -> JSONResponse:
        if exception.status_code == 401:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
        return JSONResponse(status_code=exception.status_code, content={"error": "request_error"})

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(service="cortex-api", status="ok")

    @app.post("/chat/turn", response_model=ChatTurnResponse, tags=["chat"])
    async def chat_turn(request: ChatTurnRequest) -> ChatTurnResponse | JSONResponse:
        try:
            return await resolved_chat_service.turn(request)
        except InvalidChatHistory:
            return JSONResponse(status_code=422, content={"error": "history_must_end_with_user"})
        except ModelTimeout:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "model_timeout"},
            )
        except ModelUnavailable:
            return JSONResponse(status_code=503, content={"error": "model_unavailable"})
        except InvalidModelOutput:
            return JSONResponse(status_code=502, content={"error": "invalid_model_response"})
        except ModelRejectedRequest:
            return JSONResponse(status_code=502, content={"error": "model_rejected_request"})
        except Exception:
            return JSONResponse(status_code=502, content={"error": "model_error"})

    @app.post(
        "/conversations",
        response_model=ConversationResponse,
        status_code=201,
        tags=["conversations"],
    )
    async def create_conversation(
        identity: Annotated[CallerIdentity, Depends(caller)],
    ) -> ConversationResponse:
        return await resolved_conversation_service.create(identity.owner_id)

    @app.get("/conversations", response_model=ConversationListResponse, tags=["conversations"])
    async def list_conversations(
        identity: Annotated[CallerIdentity, Depends(caller)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    ) -> ConversationListResponse:
        return await resolved_conversation_service.list(
            identity.owner_id, limit=limit, offset=offset
        )

    @app.get(
        "/conversations/{conversation_id}",
        response_model=ConversationResponse,
        tags=["conversations"],
    )
    async def get_conversation(
        conversation_id: uuid.UUID, identity: Annotated[CallerIdentity, Depends(caller)]
    ) -> ConversationResponse | JSONResponse:
        try:
            return await resolved_conversation_service.get(identity.owner_id, conversation_id)
        except ConversationNotFound:
            return JSONResponse(status_code=404, content={"error": "conversation_not_found"})

    @app.post(
        "/conversations/{conversation_id}/turns",
        response_model=AppendTurnResponse,
        tags=["conversations"],
    )
    async def append_conversation_turn(
        conversation_id: uuid.UUID,
        request: AppendTurnRequest,
        identity: Annotated[CallerIdentity, Depends(caller)],
    ) -> AppendTurnResponse | JSONResponse:
        try:
            return await resolved_conversation_service.append_turn(
                identity.owner_id, conversation_id, request.content
            )
        except ConversationNotFound:
            return JSONResponse(status_code=404, content={"error": "conversation_not_found"})
        except StaleConversationError:
            return JSONResponse(status_code=409, content={"error": "conversation_conflict"})
        except ConversationHistoryFull:
            return JSONResponse(status_code=422, content={"error": "conversation_history_full"})
        except ModelTimeout:
            return JSONResponse(status_code=503, content={"error": "model_timeout"})
        except ModelUnavailable:
            return JSONResponse(status_code=503, content={"error": "model_unavailable"})
        except InvalidModelOutput:
            return JSONResponse(status_code=502, content={"error": "invalid_model_response"})
        except ModelRejectedRequest:
            return JSONResponse(status_code=502, content={"error": "model_rejected_request"})
        except Exception:
            return JSONResponse(status_code=502, content={"error": "conversation_error"})

    @app.post(
        "/conversations/{conversation_id}/turns/stream",
        response_class=StreamingResponse,
        tags=["conversations"],
    )
    async def stream_conversation_turn(
        conversation_id: uuid.UUID,
        request_body: AppendTurnRequest,
        request: Request,
        identity: Annotated[CallerIdentity, Depends(caller)],
    ) -> StreamingResponse:
        async def events() -> AsyncGenerator[str]:
            started = time.monotonic()
            emitted_characters = 0
            outcome = "cancelled"
            logger.info("cortex_stream_start", extra={"stream_event": "start"})
            try:
                async for event in resolved_conversation_service.stream_turn(
                    identity.owner_id, conversation_id, request_body.content
                ):
                    if await request.is_disconnected():
                        return
                    if isinstance(event, ConversationTextDelta):
                        emitted_characters += len(event.text)
                        yield _sse("delta", event)
                    elif isinstance(event, ConversationStreamCompleted):
                        outcome = "completed"
                        yield _sse("completed", event)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code = {
                    ConversationNotFound: "conversation_not_found",
                    StaleConversationError: "conversation_conflict",
                    ConversationHistoryFull: "conversation_history_full",
                    ModelTimeout: "model_timeout",
                    ModelUnavailable: "model_unavailable",
                    InvalidModelOutput: "invalid_model_response",
                    ModelRejectedRequest: "model_rejected_request",
                }.get(type(error), "conversation_error")
                outcome = code
                yield _sse("error", ConversationStreamError.model_validate({"error": code}))
            finally:
                logger.info(
                    "cortex_stream_end",
                    extra={
                        "stream_event": outcome,
                        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                        "emitted_characters": emitted_characters,
                    },
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/health/brain", response_model=BrainDiagnosticResponse, tags=["system"])
    async def brain_health(request: Request) -> BrainDiagnosticResponse | JSONResponse:
        client = cast(BrainClient | None, request.app.state.brain_client)
        if client is None:
            return JSONResponse(
                status_code=503, content={"dependency": "brain", "status": "disabled"}
            )
        try:
            await client.health()
            await client.identity_context()
        except BrainRejectedCredentials:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"dependency": "brain", "status": "unauthorized"},
            )
        except BrainMalformedResponse:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"dependency": "brain", "status": "malformed"},
            )
        except BrainUnavailable:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"dependency": "brain", "status": "unavailable"},
            )
        except BrainUnexpectedResponse:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"dependency": "brain", "status": "error"},
            )
        return BrainDiagnosticResponse(status="ok")

    @app.post("/knowledge/lookup", response_model=LookupResponse, tags=["knowledge"])
    async def lookup_knowledge(
        lookup: LookupRequest,
        _: Annotated[CallerIdentity, Depends(caller)],
    ) -> LookupResponse | JSONResponse:
        if lookup_service is None:
            return JSONResponse(status_code=503, content={"error": "brain_disabled"})
        try:
            return await lookup_service.lookup(lookup.query)
        except KnowledgeChanged:
            return JSONResponse(status_code=409, content={"error": "knowledge_changed"})
        except BrainRejectedCredentials:
            return JSONResponse(status_code=502, content={"error": "brain_unauthorized"})
        except BrainMalformedResponse:
            return JSONResponse(status_code=502, content={"error": "brain_malformed"})
        except BrainUnavailable:
            return JSONResponse(status_code=503, content={"error": "brain_unavailable"})
        except BrainUnexpectedResponse:
            return JSONResponse(status_code=502, content={"error": "brain_error"})

    @app.post("/knowledge/answer", response_model=AnswerResponse, tags=["knowledge"])
    async def answer_knowledge(
        request: LookupRequest,
        _: Annotated[CallerIdentity, Depends(caller)],
    ) -> AnswerResponse | JSONResponse:
        if answer_service is None:
            return JSONResponse(status_code=503, content={"error": "brain_disabled"})
        try:
            return await answer_service.answer(request.query)
        except KnowledgeChanged:
            return JSONResponse(status_code=409, content={"error": "knowledge_changed"})
        except BrainRejectedCredentials:
            return JSONResponse(status_code=502, content={"error": "brain_unauthorized"})
        except BrainMalformedResponse:
            return JSONResponse(status_code=502, content={"error": "brain_malformed"})
        except BrainUnavailable:
            return JSONResponse(status_code=503, content={"error": "brain_unavailable"})
        except BrainUnexpectedResponse:
            return JSONResponse(status_code=502, content={"error": "brain_error"})
        except ModelTimeout:
            return JSONResponse(status_code=503, content={"error": "model_timeout"})
        except ModelUnavailable:
            return JSONResponse(status_code=503, content={"error": "model_unavailable"})
        except InvalidModelOutput:
            return JSONResponse(status_code=502, content={"error": "invalid_model_response"})
        except ModelRejectedRequest:
            return JSONResponse(status_code=502, content={"error": "model_rejected_request"})
        except Exception:
            return JSONResponse(status_code=502, content={"error": "model_error"})

    return app


app = create_app()
