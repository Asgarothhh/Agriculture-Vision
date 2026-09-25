from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LayerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    color: str = Field(default="#2E7D32", max_length=16)


class LayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    color: str | None = None
    is_visible: bool | None = None
    folder_id: UUID | None = None


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_visible: bool | None = None


class FolderItems(BaseModel):
    layer_id: UUID | None = None
    object_id: UUID | None = None
    detach: bool = False


class ObjectCreate(BaseModel):
    name: str = ""
    geom: dict[str, Any]
    origin: Literal["auto", "manual"] = "manual"


class ObjectUpdate(BaseModel):
    name: str | None = None
    geom: dict[str, Any] | None = None
    layer_id: UUID | None = None


class MergeRequest(BaseModel):
    object_ids: list[UUID] = Field(min_length=2)
    geom: dict[str, Any] | None = None


class ExportRequest(BaseModel):
    format: Literal["geojson", "kml", "shapefile", "svg"]
    layer_ids: list[UUID] | None = None
