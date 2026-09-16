from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from cortex_brain import BrainClient


class KnowledgeChanged(Exception):
    pass


class LookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class LookupResult(BaseModel):
    page_id: UUID
    page_version_id: UUID
    title: str
    path: str
    snippet: str
    content_markdown: str
    source_titles: list[str]


class LookupResponse(BaseModel):
    result: LookupResult | None


class KnowledgeLookupService:
    """Find one authorized current Brain page for a local Cortex caller."""

    def __init__(self, brain_client: BrainClient) -> None:
        self._brain_client = brain_client

    async def lookup(self, query: str) -> LookupResponse:
        search = await self._brain_client.search(query)
        if not search.results:
            return LookupResponse(result=None)
        hit = search.results[0]
        page = await self._brain_client.get_page(str(hit.page_id))
        if page.id != hit.page_id or page.current_version.id != hit.page_version_id:
            raise KnowledgeChanged
        return LookupResponse(
            result=LookupResult(
                page_id=page.id,
                page_version_id=page.current_version.id,
                title=page.title,
                path=hit.path,
                snippet=hit.snippet,
                content_markdown=page.current_version.content_markdown,
                source_titles=[item.source.title for item in page.current_version.provenance],
            )
        )
