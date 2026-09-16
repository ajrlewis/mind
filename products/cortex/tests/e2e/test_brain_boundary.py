import os
import time

import httpx
import pytest


@pytest.mark.e2e
def test_compose_cortex_reaches_brain_without_exposing_identity() -> None:
    cortex_url = os.getenv("CORTEX_TEST_URL")
    if cortex_url is None:
        pytest.skip("Set CORTEX_TEST_URL to run against the Compose boundary")

    deadline = time.monotonic() + 30
    while True:
        try:
            local = httpx.get(f"{cortex_url}/health", timeout=5)
            if local.status_code == 200:
                break
        except httpx.TransportError:
            pass
        if time.monotonic() >= deadline:
            pytest.fail("Cortex did not become healthy within 30 seconds")
        time.sleep(0.25)
    diagnostic = httpx.get(f"{cortex_url}/health/brain", timeout=10)

    assert local.status_code == 200
    assert diagnostic.status_code == 200
    assert diagnostic.json() == {"dependency": "brain", "status": "ok"}
    assert "organization_id" not in diagnostic.text
    assert "principal_id" not in diagnostic.text


@pytest.mark.e2e
def test_lookup_returns_current_authorized_northstar_evidence() -> None:
    cortex_url = os.getenv("CORTEX_TEST_URL")
    if cortex_url is None:
        pytest.skip("Set CORTEX_TEST_URL to run against the Compose boundary")

    response = httpx.post(
        f"{cortex_url}/knowledge/lookup",
        headers={
            "Authorization": f"Bearer {os.getenv('CORTEX_TEST_BEARER_TOKEN', 'cortex-local-dev')}"
        },
        json={"query": "Revenue is £45m"},
        timeout=20,
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result is not None
    assert result["title"] == "Project Orion"
    assert "£45m" in result["content_markdown"]
    assert "Project Orion operating update" in result["source_titles"]
