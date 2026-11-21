"""Data source, metadata and profiling endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, SecretStr

from reportify.api.deps import (
    get_data_source_service,
    get_metadata_service,
    get_profiling_service,
    require_auth,
)
from reportify.db.models import DataSource
from reportify.modules.connectors.data_source_service import DataSourceService
from reportify.modules.connectors.metadata import MetadataService
from reportify.modules.connectors.profiling import ProfilingService
from reportify.modules.connectors.schemas import (
    ColumnMetadataView,
    Health,
    ProfileResult,
    SyncResult,
    TableMetadataView,
)

router = APIRouter(
    prefix="/api/v1/data-sources",
    tags=["data-sources"],
    dependencies=[Depends(require_auth)],
)


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr
    ssl_mode: Literal["disable", "prefer", "require", "verify-full"] = "prefer"
    options: dict[str, Any] = Field(default_factory=dict)


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: SecretStr | None = None
    ssl_mode: Literal["disable", "prefer", "require", "verify-full"] | None = None
    options: dict[str, Any] | None = None


class DataSourceRead(BaseModel):
    id: UUID
    name: str
    type: str
    host: str | None
    port: int | None
    database: str | None
    username: str | None
    ssl_mode: str | None
    options: dict[str, Any]
    status: str
    last_tested_at: datetime | None
    last_error: str | None
    has_secret: bool


class ColumnPatch(BaseModel):
    display_name: str | None = None
    unit: str | None = None
    description: str | None = None
    user_tags: list[str] | None = None


class ProfileRequest(BaseModel):
    table: str = Field(min_length=1)
    columns: list[str] | None = None
    sample_size: int = Field(default=10_000, ge=1, le=100_000)


@router.get("", response_model=list[DataSourceRead])
async def list_data_sources(
    service: DataSourceService = Depends(get_data_source_service),
) -> list[DataSourceRead]:
    return [_to_read(data_source) for data_source in await service.list()]


@router.post("", response_model=DataSourceRead, status_code=status.HTTP_201_CREATED)
async def create_data_source(
    payload: DataSourceCreate,
    service: DataSourceService = Depends(get_data_source_service),
) -> DataSourceRead:
    data_source = await service.create(
        name=payload.name,
        host=payload.host,
        port=payload.port,
        database=payload.database,
        username=payload.username,
        password=payload.password.get_secret_value(),
        ssl_mode=payload.ssl_mode,
        options=payload.options,
    )
    return _to_read(data_source)


@router.get("/{data_source_id}", response_model=DataSourceRead)
async def get_data_source(
    data_source_id: UUID,
    service: DataSourceService = Depends(get_data_source_service),
) -> DataSourceRead:
    return _to_read(await service.get(data_source_id))


@router.patch("/{data_source_id}", response_model=DataSourceRead)
async def update_data_source(
    data_source_id: UUID,
    payload: DataSourceUpdate,
    service: DataSourceService = Depends(get_data_source_service),
) -> DataSourceRead:
    fields = payload.model_dump(exclude_unset=True, exclude={"password"})
    password = payload.password.get_secret_value() if payload.password else None
    data_source = await service.update(
        data_source_id,
        fields=fields,
        password=password,
    )
    return _to_read(data_source)


@router.delete("/{data_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disable_data_source(
    data_source_id: UUID,
    service: DataSourceService = Depends(get_data_source_service),
) -> Response:
    await service.disable(data_source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{data_source_id}/test", response_model=Health)
async def test_data_source(
    data_source_id: UUID,
    service: DataSourceService = Depends(get_data_source_service),
) -> Health:
    return await service.test(data_source_id)


@router.post("/{data_source_id}/sync", response_model=SyncResult)
async def sync_data_source(
    data_source_id: UUID,
    service: MetadataService = Depends(get_metadata_service),
) -> SyncResult:
    return await service.sync(data_source_id)


@router.get("/{data_source_id}/tables", response_model=list[TableMetadataView])
async def list_tables(
    data_source_id: UUID,
    service: MetadataService = Depends(get_metadata_service),
) -> list[TableMetadataView]:
    return await service.list_tables(data_source_id)


@router.get("/{data_source_id}/columns", response_model=TableMetadataView)
async def list_columns(
    data_source_id: UUID,
    table: str = Query(min_length=3),
    service: MetadataService = Depends(get_metadata_service),
) -> TableMetadataView:
    return await service.get_table(data_source_id, table)


@router.patch(
    "/{data_source_id}/columns/{column_id}",
    response_model=ColumnMetadataView,
)
async def patch_column(
    data_source_id: UUID,
    column_id: UUID,
    payload: ColumnPatch,
    service: MetadataService = Depends(get_metadata_service),
) -> ColumnMetadataView:
    fields_set = set(payload.model_dump(exclude_unset=True).keys())
    if not fields_set:
        raise HTTPException(status_code=422, detail="no fields to update")
    return await service.update_column(
        data_source_id,
        column_id,
        display_name=payload.display_name,
        unit=payload.unit,
        description=payload.description,
        user_tags=payload.user_tags,
        fields_set=fields_set,
    )


@router.post("/{data_source_id}/profile", response_model=ProfileResult)
async def profile_table(
    data_source_id: UUID,
    payload: ProfileRequest,
    service: ProfilingService = Depends(get_profiling_service),
) -> ProfileResult:
    return await service.profile(
        data_source_id,
        payload.table,
        columns=payload.columns,
        sample_size=payload.sample_size,
    )


def _to_read(data_source: DataSource) -> DataSourceRead:
    return DataSourceRead(
        id=data_source.id,
        name=data_source.name,
        type=data_source.type,
        host=data_source.host,
        port=data_source.port,
        database=data_source.database,
        username=data_source.username,
        ssl_mode=data_source.ssl_mode,
        options=data_source.options,
        status=data_source.status,
        last_tested_at=data_source.last_tested_at,
        last_error=data_source.last_error,
        has_secret=data_source.secret_id is not None,
    )
