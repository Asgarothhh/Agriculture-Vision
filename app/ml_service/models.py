from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.tasks_service.models import Image


class ObjectClass(Base):
    __tablename__ = "object_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_crop: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ModelRegistry(Base):
    __tablename__ = "models_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    is_loaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PolygonObject(Base):
    __tablename__ = "polygons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[int] = mapped_column(ForeignKey("models_registry.id", ondelete="RESTRICT"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("object_classes.id", ondelete="RESTRICT"), nullable=False)
    geom = mapped_column(Geometry("POLYGON"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    needs_manual_check: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    image: Mapped[Image] = relationship(back_populates="polygons")
    object_class: Mapped[ObjectClass] = relationship()
    model: Mapped[ModelRegistry] = relationship()
    crop_probabilities: Mapped[list[CropProbability]] = relationship(
        back_populates="polygon", cascade="all, delete-orphan"
    )


class CropProbability(Base):
    __tablename__ = "crop_probabilities"
    __table_args__ = (
        CheckConstraint("probability >= 0.0 AND probability <= 1.0", name="check_probability_range"),
    )

    polygon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("polygons.id", ondelete="CASCADE"), primary_key=True
    )
    crop_class_id: Mapped[int] = mapped_column(
        ForeignKey("object_classes.id", ondelete="RESTRICT"), primary_key=True
    )
    probability: Mapped[float] = mapped_column(Float, nullable=False)

    polygon: Mapped[PolygonObject] = relationship(back_populates="crop_probabilities")
    crop_class: Mapped[ObjectClass] = relationship()


class PointObject(Base):
    __tablename__ = "point_objects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[int] = mapped_column(ForeignKey("models_registry.id", ondelete="RESTRICT"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("object_classes.id", ondelete="RESTRICT"), nullable=False)
    geom = mapped_column(Geometry("POINT"), nullable=False)
    radius_approx: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_approx: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    image: Mapped[Image] = relationship(back_populates="point_objects")
    object_class: Mapped[ObjectClass] = relationship()
    model: Mapped[ModelRegistry] = relationship()
