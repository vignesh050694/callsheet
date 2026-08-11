from httpx import AsyncClient

ORGANIZATIONS_URL = "/api/v1/organizations"
SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}


async def test_create_organization_returns_created(api_client: AsyncClient) -> None:
    response = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "sun-pictures"
    assert body["organization_type"] == "production_house"
    assert body["id"]


async def test_duplicate_slug_returns_conflict(api_client: AsyncClient) -> None:
    await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    response = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert response.status_code == 409
    assert response.json()["code"] == "ResourceConflictError"


async def test_invalid_slug_is_rejected(api_client: AsyncClient) -> None:
    response = await api_client.post(
        ORGANIZATIONS_URL,
        json={**SUN_PICTURES_PAYLOAD, "slug": "Sun Pictures!"},
    )

    assert response.status_code == 422


async def test_list_organizations_is_paginated(api_client: AsyncClient) -> None:
    await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    await api_client.post(
        ORGANIZATIONS_URL,
        json={"name": "Talent Co", "slug": "talent-co", "organization_type": "agency"},
    )

    response = await api_client.get(ORGANIZATIONS_URL, params={"limit": 1, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1


async def test_get_missing_organization_returns_not_found(api_client: AsyncClient) -> None:
    response = await api_client.get(f"{ORGANIZATIONS_URL}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_update_organization_changes_name(api_client: AsyncClient) -> None:
    created = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    organization_id = created.json()["id"]

    response = await api_client.patch(
        f"{ORGANIZATIONS_URL}/{organization_id}",
        json={"name": "Sun Pictures Pvt Ltd"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Sun Pictures Pvt Ltd"


async def test_delete_organization_returns_no_content(api_client: AsyncClient) -> None:
    created = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    organization_id = created.json()["id"]

    response = await api_client.delete(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 204
    follow_up = await api_client.get(f"{ORGANIZATIONS_URL}/{organization_id}")
    assert follow_up.status_code == 404
