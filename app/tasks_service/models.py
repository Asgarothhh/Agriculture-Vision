from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.ml_service.models import PointObject, PolygonObject
    from app.users_service.models import User


class ProcessingTask(Base):
    __tablename__ = "processing_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    aoi = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="tasks")
    image: Mapped[Optional[Image]] = relationship(
        back_populates="task", uselist=False, cascade="all, delete-orphan"
    )


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    image_type: Mapped[str] = mapped_column(String(50), nullable=False)
    crs: Mapped[str] = mapped_column(String(50), nullable=False, default="EPSG:4326")
    coverage_area: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    task: Mapped[ProcessingTask] = relationship(back_populates="image")
    polygons: Mapped[list[PolygonObject]] = relationship(back_populates="image", cascade="all, delete-orphan")
    point_objects: Mapped[list[PointObject]] = relationship(back_populates="image", cascade="all, delete-orphan")
