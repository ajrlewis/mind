from collections.abc import AsyncIterator, Sequence
from typing import cast

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from openai.types.responses import Response
from openai.types.responses.response_input_item_param import ResponseInputItemParam

from cortex_ai.errors import (
    InvalidModelOutput,
    ModelRejectedRequest,
    ModelTimeout,
    ModelUnavailable,
)
from cortex_ai.models import (
    AssistantTextDelta,
    ChatMessage,
    ModelResponse,
    ModelStreamCompleted,
    TokenUsage,
)


class OpenAIChatModel:
    """Bounded OpenAI Responses API adapter for complete and streamed turns."""

    def __init__(self, *, client: AsyncOpenAI, model: str, owns_client: bool = False) -> None:
        self._client = client
        self._model = model
        self._owns_client = owns_client

    async def invoke(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        provider_messages = cast(
            list[ResponseInputItemParam],
            [{"role": message.role, "content": message.content} for message in messages],
        )
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=provider_messages,
                store=False,
            )
        except APITimeoutError as error:
            raise ModelTimeout from error
        except APIResponseValidationError as error:
            raise InvalidModelOutput from error
        except (
            AuthenticationError,
            PermissionDeniedError,
            BadRequestError,
            ConflictError,
            NotFoundError,
            UnprocessableEntityError,
        ) as error:
            raise ModelRejectedRequest from error
        except RateLimitError as error:
            raise ModelUnavailable from error
        except APIConnectionError as error:
            raise ModelUnavailable from error
        except APIStatusError as error:
            raise ModelUnavailable from error
        except APIError as error:
            raise ModelUnavailable from error
        except Exception as error:
            raise ModelUnavailable from error

        return self._translate_response(response)

    async def stream(
        self, messages: Sequence[ChatMessage]
    ) -> AsyncIterator[AssistantTextDelta | ModelStreamCompleted]:
        provider_messages = cast(
            list[ResponseInputItemParam],
            [{"role": message.role, "content": message.content} for message in messages],
        )
        terminal = False
        emitted: list[str] = []
        provider_stream = None
        try:
            provider_stream = await self._client.responses.create(
                model=self._model, input=provider_messages, store=False, stream=True
            )
            async for event in provider_stream:
                event_type = getattr(event, "type", None)
                if terminal:
                    raise InvalidModelOutput
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", None)
                    if not isinstance(delta, str) or not delta:
                        raise InvalidModelOutput
                    emitted.append(delta)
                    yield AssistantTextDelta(text=delta)
                elif event_type == "response.completed":
                    response = getattr(event, "response", None)
                    if response is None:
                        raise InvalidModelOutput
                    validated = self._translate_response(response)
                    if "".join(emitted) != validated.message.content:
                        raise InvalidModelOutput
                    terminal = True
                    yield ModelStreamCompleted(
                        message=validated.message,
                        model=validated.model,
                        usage=validated.usage,
                    )
                elif event_type in {"response.failed", "response.incomplete", "error"}:
                    raise InvalidModelOutput
            if not terminal:
                raise InvalidModelOutput
        except (InvalidModelOutput, ModelTimeout, ModelUnavailable, ModelRejectedRequest):
            raise
        except APITimeoutError as error:
            raise ModelTimeout from error
        except APIResponseValidationError as error:
            raise InvalidModelOutput from error
        except (
            AuthenticationError,
            PermissionDeniedError,
            BadRequestError,
            ConflictError,
            NotFoundError,
            UnprocessableEntityError,
        ) as error:
            raise ModelRejectedRequest from error
        except (RateLimitError, APIConnectionError, APIStatusError, APIError) as error:
            raise ModelUnavailable from error
        except Exception as error:
            raise ModelUnavailable from error
        finally:
            if provider_stream is not None:
                await provider_stream.close()

    @staticmethod
    def _translate_response(response: Response) -> ModelResponse:
        try:
            if response.status != "completed" or len(response.output) != 1:
                raise InvalidModelOutput
            output = response.output[0]
            if output.type != "message" or output.role != "assistant" or len(output.content) != 1:
                raise InvalidModelOutput
            content = output.content[0]
            if content.type != "output_text":
                raise InvalidModelOutput

            usage = None
            if response.usage is not None:
                usage = TokenUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
            return ModelResponse(
                message=ChatMessage(role="assistant", content=content.text),
                model=response.model,
                usage=usage,
            )
        except InvalidModelOutput:
            raise
        except Exception as error:
            raise InvalidModelOutput from error

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()


def create_openai_chat_model(
    *,
    api_key: str,
    model: str,
    timeout_seconds: float,
    base_url: str | None = None,
    organization: str | None = None,
    project: str | None = None,
) -> OpenAIChatModel:
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        organization=organization,
        project=project,
        timeout=timeout_seconds,
        max_retries=0,
    )
    return OpenAIChatModel(client=client, model=model, owns_client=True)
