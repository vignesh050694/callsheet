from httpx import AsyncClient


async def test_health_returns_ok(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


async def test_response_carries_request_id_header(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/health")

    assert response.headers.get("X-Request-ID")
