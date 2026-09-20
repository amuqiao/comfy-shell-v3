from fastapi.testclient import TestClient


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-service-key"}


def test_items_crud_flow(sqlite_app):
    with TestClient(sqlite_app) as client:
        created = client.post(
            "/v1/items",
            json={"name": "alpha", "description": "first", "status": "active"},
            headers=auth_headers(),
        )
        assert created.status_code == 201
        item = created.json()["data"]
        assert item["name"] == "alpha"
        assert item["version"] == 1

        fetched = client.get(f"/v1/items/{item['id']}", headers=auth_headers())
        assert fetched.status_code == 200
        assert fetched.json()["data"]["id"] == item["id"]

        listed = client.get("/v1/items", headers=auth_headers())
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["data"]["items"]] == [item["id"]]

        updated = client.patch(
            f"/v1/items/{item['id']}",
            json={"expected_version": 1, "description": "second", "status": "archived"},
            headers=auth_headers(),
        )
        assert updated.status_code == 200
        updated_item = updated.json()["data"]
        assert updated_item["description"] == "second"
        assert updated_item["status"] == "archived"
        assert updated_item["version"] == 2

        deleted = client.request(
            "DELETE",
            f"/v1/items/{item['id']}",
            json={"expected_version": 2},
            headers=auth_headers(),
        )
        assert deleted.status_code == 200
        assert deleted.json()["data"]["version"] == 3

        missing = client.get(f"/v1/items/{item['id']}", headers=auth_headers())
        assert missing.status_code == 404
        assert missing.json()["code"] == "ITEM_NOT_FOUND"


def test_item_name_conflict(sqlite_app):
    with TestClient(sqlite_app) as client:
        first = client.post("/v1/items", json={"name": "dup"}, headers=auth_headers())
        second = client.post("/v1/items", json={"name": "dup"}, headers=auth_headers())

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "ITEM_NAME_CONFLICT"


def test_item_version_conflict(sqlite_app):
    with TestClient(sqlite_app) as client:
        created = client.post("/v1/items", json={"name": "versioned"}, headers=auth_headers())
        item_id = created.json()["data"]["id"]
        conflict = client.patch(
            f"/v1/items/{item_id}",
            json={"expected_version": 2, "description": "stale"},
            headers=auth_headers(),
        )

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "ITEM_VERSION_CONFLICT"


def test_items_cursor_pagination(sqlite_app):
    with TestClient(sqlite_app) as client:
        first = client.post("/v1/items", json={"name": "one"}, headers=auth_headers()).json()["data"]
        second = client.post("/v1/items", json={"name": "two"}, headers=auth_headers()).json()["data"]

        page1 = client.get("/v1/items", params={"limit": 1}, headers=auth_headers())
        assert page1.status_code == 200
        body1 = page1.json()["data"]
        assert len(body1["items"]) == 1
        assert body1["next_cursor"]

        page2 = client.get("/v1/items", params={"limit": 1, "cursor": body1["next_cursor"]}, headers=auth_headers())
        assert page2.status_code == 200
        body2 = page2.json()["data"]
        assert len(body2["items"]) == 1
        assert {body1["items"][0]["id"], body2["items"][0]["id"]} == {first["id"], second["id"]}


def test_items_invalid_cursor_returns_request_invalid(sqlite_app):
    with TestClient(sqlite_app) as client:
        response = client.get("/v1/items", params={"cursor": "not-a-cursor"}, headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_items_invalid_status_returns_request_invalid(sqlite_app):
    with TestClient(sqlite_app) as client:
        response = client.get("/v1/items", params={"status": "unknown"}, headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_soft_deleted_name_can_be_reused(sqlite_app):
    with TestClient(sqlite_app) as client:
        created = client.post("/v1/items", json={"name": "reuse"}, headers=auth_headers()).json()["data"]
        deleted = client.request(
            "DELETE",
            f"/v1/items/{created['id']}",
            json={"expected_version": created["version"]},
            headers=auth_headers(),
        )
        recreated = client.post("/v1/items", json={"name": "reuse"}, headers=auth_headers())

    assert deleted.status_code == 200
    assert recreated.status_code == 201
    assert recreated.json()["data"]["id"] != created["id"]


def test_items_requires_auth(sqlite_app):
    with TestClient(sqlite_app) as client:
        response = client.post("/v1/items", json={"name": "secure"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
