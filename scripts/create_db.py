import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    create_engine,
    text,
    ForeignKey,
    String,
    Integer,
    Boolean,
    Float,
    DateTime,
    CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from geoalchemy2 import Geometry


DB_USER = "postgres"
DB_PASSWORD = "ВАШ_ПАРОЛЬ_ЗДЕСЬ"  
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "agro_analysis_db"


class Base(DeclarativeBase):
    pass


class Role(Base):
    __tablename__ = 'roles'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class User(Base):
    __tablename__ = 'users'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey('roles.id', ondelete='RESTRICT'), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ProcessingTask(Base):
    __tablename__ = 'processing_tasks'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default='PENDING', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Image(Base):
    __tablename__ = 'images'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # index=True создаст индекс для ускорения выборок по FK (idx_images_task_id)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('processing_tasks.id', ondelete='CASCADE'), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    image_type: Mapped[str] = mapped_column(String(50), nullable=False)
    crs: Mapped[str] = mapped_column(String(50), nullable=False)
    coverage_area: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ObjectClass(Base):
    __tablename__ = 'object_classes'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(50), nullable=False)


class ModelsRegistry(Base):
    __tablename__ = 'models_registry'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)


class PolygonObject(Base):
    __tablename__ = 'polygons'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('images.id', ondelete='CASCADE'), nullable=False, index=True)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey('models_registry.id', ondelete='RESTRICT'), nullable=False)
    class_id: Mapped[int] = mapped_column(Integer, ForeignKey('object_classes.id', ondelete='RESTRICT'), nullable=False)
    # GeoAlchemy2 автоматически создает пространственный GiST-индекс для Geometry колонок
    geom: Mapped[str] = mapped_column(Geometry('POLYGON'), nullable=False)
    needs_manual_check: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CropProbability(Base):
    __tablename__ = 'crop_probabilities'
    
    polygon_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('polygons.id', ondelete='CASCADE'), primary_key=True)
    crop_class_id: Mapped[int] = mapped_column(Integer, ForeignKey('object_classes.id', ondelete='RESTRICT'), primary_key=True)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    
    __table_args__ = (
        CheckConstraint('probability >= 0.0 AND probability <= 1.0', name='check_probability_range'),
    )


class PointObject(Base):
    __tablename__ = 'point_objects'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('images.id', ondelete='CASCADE'), nullable=False, index=True)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey('models_registry.id', ondelete='RESTRICT'), nullable=False)
    class_id: Mapped[int] = mapped_column(Integer, ForeignKey('object_classes.id', ondelete='RESTRICT'), nullable=False)
    # Пространственный GiST-индекс будет создан автоматически
    geom: Mapped[str] = mapped_column(Geometry('POINT'), nullable=False)
    radius_approx: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_approx: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


def main():
    # Шаг 1. Проверяем существование целевой БД (через дефолтное системное подключение к 'postgres')
    base_url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
    engine_base = create_engine(base_url, isolation_level="AUTOCOMMIT")
    
    print("Проверка наличия базы данных на сервере...")
    with engine_base.connect() as conn:
        result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'"))
        if not result.scalar():
            conn.execute(text(f"CREATE DATABASE {DB_NAME}"))
            print(f"-> База данных '{DB_NAME}' успешно создана.")
        else:
            print(f"-> База данных '{DB_NAME}' уже существует.")
    engine_base.dispose()

    # Шаг 2. Подключаемся непосредственно к созданной базе данных agro_analysis_db
    db_url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(db_url)
    
    # Шаг 3. Инициализация расширения PostGIS
    print("Инициализация расширения PostGIS...")
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
    print("-> Расширение PostGIS готово к работе.")

    # Шаг 4. Создание таблиц и индексов на основе ORM моделей
    print("Создание таблиц и индексов в базе данных...")
    Base.metadata.create_all(engine)
    print("-> Структура таблиц и индексы успешно развернуты.")

    # Шаг 5. Первичное наполнение (сидирование) справочников данными
    print("Заполнение справочников начальными данными...")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        # Наполнение ролей
        if not session.query(Role).first():
            session.add_all([
                Role(name='Admin'),
                Role(name='Agro_Expert'),
                Role(name='Operator')
            ])
            print("   - Добавлены базовые роли.")

        # Наполнение классов пространственных объектов
        if not session.query(ObjectClass).first():
            session.add_all([
                ObjectClass(id=1, name='Пашня (Культурные растения)', geometry_type='POLYGON'),
                ObjectClass(id=2, name='Залежь', geometry_type='POLYGON'),
                ObjectClass(id=5, name='Отдельно стоящее дерево', geometry_type='POINT'),
                ObjectClass(id=6, name='Столб ЛЭП', geometry_type='POINT')
            ])
            print("   - Добавлен реестр классов объектов.")

        # Наполнение реестра ML-моделей
        if not session.query(ModelsRegistry).first():
            session.add_all([
                ModelsRegistry(name='SegFormer_Fields_v1.0', task_type='SEGMENTATION'),
                ModelsRegistry(name='YOLOv8x_Infra_v2.1', task_type='DETECTION')
            ])
            print("   - Зарегистрированы стартовые ML-модели.")
            
        session.commit()
    
    print("\n[УСПЕХ] База данных полностью готова к интеграции с вашим Python-приложением!")


if __name__ == "__main__":
    main()
