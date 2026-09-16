from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from cortex_api import create_app
from cortex_api.settings import Settings
from cortex_brain import BrainClient

PAGE_ID = "10000000-0000-0000-0000-000000000001"
VERSION_ID = "20000000-0000-0000-0000-000000000001"
TOKEN = "synthetic-brain-token"
CORTEX_HEADERS = {"Authorization": "Bearer cortex-local-dev"}


def app_client(handler: httpx.MockTransport) -> TestClient:
    brain = BrainClient(
        base_url="http://brain.test",
        api_key=TOKEN,
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        http_client=httpx.AsyncClient(transport=handler, base_url="http://brain.test"),
    )
    return TestClient(create_app(brain_client=brain))


def test_lookup_searches_then_reads_authorized_current_page() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/search":
            assert request.method == "POST"
            assert request.read() == b'{"query":"Orion","limit":1}'
            return httpx.Response(
                200,
                json={
                    "query": "Orion",
                    "results": [
                        {
                            "page_id": PAGE_ID,
                            "page_version_id": VERSION_ID,
                            "title": "Project Orion",
                            "path": "portfolio/project-orion",
                            "snippet": "Synthetic project",
                        }
                    ],
                },
            )
        assert request.url.path == f"/pages/{PAGE_ID}"
        return httpx.Response(
            200,
            json={
                "id": PAGE_ID,
                "title": "Project Orion",
                "current_version": {
                    "id": VERSION_ID,
                    "content_markdown": "# Synthetic project",
                    "provenance": [{"source": {"title": "Synthetic memo"}}],
                },
            },
        )

    client = app_client(httpx.MockTransport(handler))
    assert client.post("/knowledge/lookup", json={"query": "Orion"}).status_code == 401
    response = client.post("/knowledge/lookup", headers=CORTEX_HEADERS, json={"query": "Orion"})

    assert response.status_code == 200
    assert paths == ["/search", f"/pages/{PAGE_ID}"]
    assert response.json()["result"] == {
        "page_id": PAGE_ID,
        "page_version_id": VERSION_ID,
        "title": "Project Orion",
        "path": "portfolio/project-orion",
        "snippet": "Synthetic project",
        "content_markdown": "# Synthetic project",
        "source_titles": ["Synthetic memo"],
    }
    assert TOKEN not in response.text


def test_lookup_empty_result_never_reads_a_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        return httpx.Response(200, json={"query": "missing", "results": []})

    response = app_client(httpx.MockTransport(handler)).post(
        "/knowledge/lookup", headers=CORTEX_HEADERS, json={"query": "missing"}
    )
    assert response.status_code == 200
    assert response.json() == {"result": None}


def test_lookup_requires_valid_query_and_configured_brain() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid input must not call Brain")

    client = app_client(httpx.MockTransport(fail))
    invalid = client.post("/knowledge/lookup", headers=CORTEX_HEADERS, json={"query": "  "})
    assert invalid.status_code == 422
    assert invalid.json() == {"error": "invalid_request"}

    disabled = TestClient(create_app(settings=Settings())).post(
        "/knowledge/lookup", headers=CORTEX_HEADERS, json={"query": "Orion"}
    )
    assert disabled.status_code == 503
    assert disabled.json() == {"error": "brain_disabled"}


@pytest.mark.parametrize("failure", ["stale", "denied", "malformed"])
def test_lookup_fails_closed_on_changed_or_unreadable_page(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "page_id": PAGE_ID,
                            "page_version_id": VERSION_ID,
                            "title": "Project Orion",
                            "path": "portfolio/orion",
                            "snippet": "Synthetic",
                        }
                    ]
                },
            )
        if failure == "denied":
            return httpx.Response(403, text="private upstream detail")
        if failure == "malformed":
            return httpx.Response(200, json={"id": PAGE_ID})
        return httpx.Response(
            200,
            json={
                "id": PAGE_ID,
                "title": "Project Orion",
                "current_version": {
                    "id": str(UUID(int=3)),
                    "content_markdown": "changed",
                    "provenance": [],
                },
            },
        )

    response = app_client(httpx.MockTransport(handler)).post(
        "/knowledge/lookup", headers=CORTEX_HEADERS, json={"query": "Orion"}
    )
    assert response.status_code == {"stale": 409, "denied": 502, "malformed": 502}[failure]
    assert response.json() == {
        "error": {
            "stale": "knowledge_changed",
            "denied": "brain_unauthorized",
            "malformed": "brain_malformed",
        }[failure]
    }
    assert "private upstream detail" not in response.text
