from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from cortex_brain.errors import (
    BrainMalformedResponse,
    BrainRejectedCredentials,
    BrainUnavailable,
    BrainUnexpectedResponse,
)
from cortex_brain.models import (
    BrainHealth,
    BrainIdentityContext,
    BrainPage,
    BrainSearchResponse,
)

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class BrainClient:
    """Typed client for the small public Brain surface Cortex currently consumes."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=read_timeout_seconds,
                pool=connect_timeout_seconds,
            ),
        )
        self._authorization = f"Bearer {api_key}"

    async def health(self) -> BrainHealth:
        return await self._get("/health", BrainHealth, authenticated=False)

    async def identity_context(self) -> BrainIdentityContext:
        return await self._get("/auth/context", BrainIdentityContext, authenticated=True)

    async def search(self, query: str) -> BrainSearchResponse:
        return await self._request(
            "POST", "/search", BrainSearchResponse, json={"query": query, "limit": 1}
        )

    async def get_page(self, page_id: str) -> BrainPage:
        return await self._get(f"/pages/{page_id}", BrainPage, authenticated=True)

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def _get(
        self, path: str, model: type[ResponseModel], *, authenticated: bool
    ) -> ResponseModel:
        headers = {"Authorization": self._authorization} if authenticated else None
        return await self._request("GET", path, model, headers=headers)

    async def _request(
        self,
        method: str,
        path: str,
        model: type[ResponseModel],
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> ResponseModel:
        if method == "POST":
            headers = {"Authorization": self._authorization}
        try:
            response = await self._http_client.request(method, path, headers=headers, json=json)
        except httpx.TransportError as exc:
            raise BrainUnavailable("Brain is unavailable") from exc

        if response.status_code in {401, 403}:
            raise BrainRejectedCredentials("Brain rejected Cortex credentials")
        if response.status_code != 200:
            raise BrainUnexpectedResponse("Brain returned an unexpected status")
        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise BrainMalformedResponse("Brain returned a malformed response") from exc
