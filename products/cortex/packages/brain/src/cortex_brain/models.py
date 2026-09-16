from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CortexBrainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrainHealth(CortexBrainModel):
    status: Literal["ok"]
    service: str
    environment: str


class BrainIdentityContext(CortexBrainModel):
    organization_id: UUID
    principal_id: UUID
    group_ids: tuple[UUID, ...]


class BrainSearchResult(BaseModel):
    page_id: UUID
    page_version_id: UUID
    title: str
    path: str
    snippet: str


class BrainSearchResponse(BaseModel):
    results: list[BrainSearchResult]


class BrainSource(BaseModel):
    title: str


class BrainProvenance(BaseModel):
    source: BrainSource


class BrainPageVersion(BaseModel):
    id: UUID
    content_markdown: str
    provenance: list[BrainProvenance]


class BrainPage(BaseModel):
    id: UUID
    title: str
    current_version: BrainPageVersion
