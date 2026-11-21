from __future__ import annotations

import asyncpg
from sqlalchemy.engine import make_url


async def test_data_source_api_flow(
    client,
    sample_schema: str,
    database_url: str,
) -> None:
    url = make_url(database_url)
    assert url.username and url.password and url.database
    name = f"api_{sample_schema}"

    response = client.post(
        "/api/v1/data-sources",
        json={
            "name": name,
            "host": url.host or "127.0.0.1",
            "port": url.port or 5432,
            "database": url.database,
            "username": url.username,
            "password": url.password,
            "ssl_mode": "disable",
            "options": {"schema_allowlist": [sample_schema]},
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert "password" not in payload
    assert payload["has_secret"] is True
    data_source_id = payload["id"]

    ciphertext = await _secret_ciphertext(database_url, f"data-source:{name}")
    assert ciphertext != url.password.encode()

    assert client.post(f"/api/v1/data-sources/{data_source_id}/test").json() == {
        "ok": True,
        "detail": None,
    }

    sync = client.post(f"/api/v1/data-sources/{data_source_id}/sync")
    assert sync.status_code == 200
    assert sync.json()["tables_added"] == 1

    tables = client.get(f"/api/v1/data-sources/{data_source_id}/tables")
    assert tables.status_code == 200
    assert any(table["table_name"] == "events" for table in tables.json())

    columns = client.get(
        f"/api/v1/data-sources/{data_source_id}/columns",
        params={"table": f"{sample_schema}.events"},
    )
    assert columns.status_code == 200
    column_payload = columns.json()
    duration = next(
        column for column in column_payload["columns"] if column["column_name"] == "duration"
    )

    patched = client.patch(
        f"/api/v1/data-sources/{data_source_id}/columns/{duration['id']}",
        json={
            "display_name": "请求耗时",
            "unit": "秒",
            "description": "API 请求处理时长",
            "user_tags": ["核心指标"],
        },
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "请求耗时"
    assert patched.json()["user_tags"] == ["核心指标"]

    profile = client.post(
        f"/api/v1/data-sources/{data_source_id}/profile",
        json={"table": f"{sample_schema}.events", "sample_size": 10},
    )
    assert profile.status_code == 200
    profile_payload = profile.json()
    assert profile_payload["sampled_rows"] == 10
    assert profile_payload["lineage"]["snapshot_id"] is not None


async def _secret_ciphertext(database_url: str, name: str) -> bytes:
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    connection = await asyncpg.connect(dsn)
    try:
        value = await connection.fetchval(
            "SELECT ciphertext FROM secret WHERE name = $1",
            name,
        )
    finally:
        await connection.close()
    assert value is not None
    return bytes(value)
