from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SyncSessionLocal, import_all_models
from app.core.geo import wkb_element
from app.core.security import hash_password
from app.layers_service.models import Folder, Layer, LayerObject
from app.ml_service.models import CropProbability, ModelRegistry, ObjectClass, PointObject, PolygonObject
from app.tasks_service.models import Image, ProcessingTask
from app.users_service.models import ActivityLog, Role, User

import_all_models()

ROLES = ("Администратор", "Агроном", "Оператор")

DEMO_PASSWORD = "ValidPass1!"
DEMO_USERS = (
    {
        "email": "admin@agrovision.dev",
        "role": "Администратор",
        "first_name": "Анна",
        "last_name": "Админова",
        "organization": "АгроВижион",
    },
    {
        "email": "agronom@agrovision.dev",
        "role": "Агроном",
        "first_name": "Пётр",
        "last_name": "Полевой",
        "organization": "КФХ Заречье",
    },
    {
        "email": "operator@agrovision.dev",
        "role": "Оператор",
        "first_name": "Олег",
        "last_name": "Съёмкин",
        "organization": "КФХ Заречье",
    },
)

FIELD_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[27.45, 53.88], [27.48, 53.88], [27.48, 53.90], [27.45, 53.90], [27.45, 53.88]]],
}
TREE_POINT = {"type": "Point", "coordinates": [27.46, 53.89]}

OBJECT_CLASSES: list[dict] = [
    {"id": 1, "name": "Следы почвообработки", "geometry_type": "POLYGON", "is_crop": False},
    {"id": 2, "name": "Культурные растения", "geometry_type": "POLYGON", "is_crop": False},
    {"id": 3, "name": "Кустарник", "geometry_type": "POLYGON", "is_crop": False},
    {"id": 4, "name": "Водоём", "geometry_type": "POLYGON", "is_crop": False},
    {"id": 5, "name": "Дерево", "geometry_type": "POINT", "is_crop": False},
    {"id": 6, "name": "Столб", "geometry_type": "POINT", "is_crop": False},
    {"id": 10, "name": "Пшеница", "geometry_type": "POLYGON", "is_crop": True},
    {"id": 11, "name": "Кукуруза", "geometry_type": "POLYGON", "is_crop": True},
    {"id": 12, "name": "Соя", "geometry_type": "POLYGON", "is_crop": True},
    {"id": 13, "name": "Подсолнечник", "geometry_type": "POLYGON", "is_crop": True},
    {"id": 14, "name": "Рапс", "geometry_type": "POLYGON", "is_crop": True},
    {"id": 15, "name": "Ячмень", "geometry_type": "POLYGON", "is_crop": True},
]

MODELS = [
    {"name": "SegFormer_v1.0", "code": "segformer", "task_type": "SEGMENTATION", "version": "1.0"},
    {"name": "YOLO-seg26", "code": "yolo_seg_26", "task_type": "DETECTION", "version": "1.0"},
]

SYSTEM_LAYERS = [
    {"name": "Следы почвообработки", "color": "#8D6E63", "class_id": 1},
    {"name": "Культурные растения", "color": "#43A047", "class_id": 2},
    {"name": "Кустарник", "color": "#2E7D32", "class_id": 3},
    {"name": "Водоём", "color": "#1E88E5", "class_id": 4},
    {"name": "Дерево", "color": "#6D4C41", "class_id": 5},
    {"name": "Столб", "color": "#546E7A", "class_id": 6},
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_system_layers(session: Session, user: User) -> None:
    existing = {
        row.class_id
        for row in session.scalars(
            select(Layer).where(Layer.user_id == user.id, Layer.kind == "auto")
        )
    }
    for item in SYSTEM_LAYERS:
        if item["class_id"] in existing:
            continue
        session.add(
            Layer(
                user_id=user.id,
                name=item["name"],
                color=item["color"],
                kind="auto",
                class_id=item["class_id"],
                is_visible=True,
            )
        )


def _ensure_user(session: Session, spec: dict) -> User:
    legacy = spec["email"].replace("@agrovision.dev", "@agrovision.test")
    user = session.scalar(select(User).where(User.username.in_([spec["email"], legacy])))
    if user is not None and user.username != spec["email"]:
        user.username = spec["email"]
    role = session.scalar(select(Role).where(Role.name == spec["role"]))
    if role is None:
        raise RuntimeError(f"Role {spec['role']} is missing; run seed() first")
    if user is None:
        user = User(
            username=spec["email"],
            first_name=spec["first_name"],
            last_name=spec["last_name"],
            organization=spec["organization"],
            user_role=spec["role"],
            password_hash=hash_password(DEMO_PASSWORD),
            role_id=role.id,
            is_active=True,
        )
        session.add(user)
        session.flush()
        session.add(
            ActivityLog(
                user_id=user.id,
                category="account",
                action="Демо-регистрация",
                payload={"email": user.username},
            )
        )
    ensure_system_layers(session, user)
    return user


def _ensure_agronom_demo(session: Session, user: User) -> None:
    folder = session.scalar(
        select(Folder).where(Folder.user_id == user.id, Folder.name == "Сезон 2026")
    )
    if folder is None:
        folder = Folder(user_id=user.id, name="Сезон 2026", is_visible=True)
        session.add(folder)
        session.flush()

    layer = session.scalar(
        select(Layer).where(Layer.user_id == user.id, Layer.name == "Демо поле", Layer.kind == "user")
    )
    if layer is None:
        layer = Layer(
            user_id=user.id,
            folder_id=folder.id,
            name="Демо поле",
            color="#FF9800",
            kind="user",
            is_visible=True,
        )
        session.add(layer)
        session.flush()

    objects_exist = session.scalar(select(LayerObject.id).where(LayerObject.layer_id == layer.id).limit(1))
    if objects_exist is None:
        session.add(
            LayerObject(
                layer_id=layer.id,
                folder_id=folder.id,
                name="Поле 1",
                number=1,
                geom=wkb_element(FIELD_POLYGON, 4326),
                area_ha=2.4,
                is_point=False,
                origin="manual",
            )
        )
        session.add(
            LayerObject(
                layer_id=layer.id,
                folder_id=folder.id,
                name="Дерево у края",
                number=2,
                geom=wkb_element(TREE_POINT, 4326),
                is_point=True,
                origin="manual",
            )
        )

    model = session.scalar(select(ModelRegistry).where(ModelRegistry.code == "segformer"))
    if model is None:
        raise RuntimeError("models_registry is empty")

    demo_prefix = "demo/agronom/"
    existing_paths = {
        row.file_path
        for row in session.scalars(select(Image).join(ProcessingTask).where(ProcessingTask.user_id == user.id))
        if row.file_path.startswith(demo_prefix)
    }

    def add_task(status: str, filename: str, *, error: str | None = None) -> Image | None:
        path = f"{demo_prefix}{filename}"
        if path in existing_paths:
            return None
        now = _utcnow()
        task = ProcessingTask(
            user_id=user.id,
            model_name="segformer",
            confidence_threshold=0.5,
            aoi=wkb_element(FIELD_POLYGON, 4326),
            status=status,
            progress=100 if status == "COMPLETED" else (0 if status == "PENDING" else 0),
            error=error,
            completed_at=now if status == "COMPLETED" else None,
            expires_at=now + timedelta(days=30),
        )
        session.add(task)
        session.flush()
        image = Image(
            task_id=task.id,
            file_path=path,
            image_type="RGB",
            crs="EPSG:4326",
            coverage_area=0.03,
            is_valid=True,
            width=1024,
            height=1024,
        )
        session.add(image)
        session.flush()
        session.add(
            ActivityLog(
                user_id=user.id,
                category="upload_processing",
                action=f"Демо-задача {status}",
                payload={"task_id": str(task.id), "status": status},
            )
        )
        return image

    add_task("PENDING", "pending.png")
    add_task("FAILED", "failed.png", error="Демо: обработка прервана")
    completed_image = add_task("COMPLETED", "completed.png")
    if completed_image is not None:
        poly = PolygonObject(
            image_id=completed_image.id,
            model_id=model.id,
            class_id=2,
            geom=wkb_element(FIELD_POLYGON, 4326),
            confidence=0.86,
            needs_manual_check=False,
        )
        session.add(poly)
        session.flush()
        session.add(CropProbability(polygon_id=poly.id, crop_class_id=10, probability=0.72))
        session.add(CropProbability(polygon_id=poly.id, crop_class_id=11, probability=0.28))
        session.add(
            PointObject(
                image_id=completed_image.id,
                model_id=model.id,
                class_id=5,
                geom=wkb_element(TREE_POINT, 4326),
                radius_approx=3.2,
                area_approx=32.0,
                confidence=0.91,
            )
        )


def seed(session: Session | None = None) -> None:
    own_session = session is None
    session = session or SyncSessionLocal()
    try:
        for name in ROLES:
            if session.scalar(select(Role).where(Role.name == name)) is None:
                session.add(Role(name=name))
        session.flush()

        for item in OBJECT_CLASSES:
            if session.get(ObjectClass, item["id"]) is None:
                session.add(ObjectClass(**item))

        for item in MODELS:
            if session.scalar(select(ModelRegistry).where(ModelRegistry.code == item["code"])) is None:
                session.add(ModelRegistry(**item))

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def seed_demo(session: Session | None = None) -> None:
    own_session = session is None
    session = session or SyncSessionLocal()
    try:
        users = {spec["role"]: _ensure_user(session, spec) for spec in DEMO_USERS}
        _ensure_agronom_demo(session, users["Агроном"])
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def main() -> None:
    seed()
    seed_demo()
    print("Seed complete: roles, object_classes, models_registry, demo users")


if __name__ == "__main__":
    main()
