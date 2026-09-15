from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_MESSAGES = 50
MAX_MESSAGE_CHARACTERS = 8_000
MAX_ASSISTANT_RESPONSE_CHARACTERS = 32_000

MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARACTERS),
]
ModelIdentity = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: MessageText


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: ChatMessage
    model: ModelIdentity
    usage: TokenUsage | None = None


class AssistantTextDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: Annotated[str, StringConstraints(min_length=1)]


class ModelStreamCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message: ChatMessage
    model: ModelIdentity
    usage: TokenUsage | None = None


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)


class ChatTurnResponse(ModelResponse):
    pass
