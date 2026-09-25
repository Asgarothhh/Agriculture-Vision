from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"
    secret_key: str = "dev-only-secret-change-me"
    encryption_key: str = "dev-only-encryption-key-32b!!"
    access_token_ttl_min: int = 30
    refresh_token_ttl_days: int = 30
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost,http://localhost:8000"
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agriculture-vision"
    postgres_user: str = "developer"
    postgres_password: str = "developer"
    database_url: str = "postgresql+asyncpg://developer:developer@localhost:5432/agriculture-vision"
    database_sync_url: str = "postgresql://developer:developer@localhost:5432/agriculture-vision"

    redis_url: str = "redis://localhost:6379/0"
    celery_queue_cpu: str = "cpu"
    celery_queue_gpu: str = "ml-gpu"

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "agrovision"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    local_storage_dir: str = "data/uploads"

    yolo_weights_path: str = "config/yolo_best.pt"
    segformer_weights_path: str = "config/segformer_best.pt"
    max_upload_mb: int = 512
    max_saved_tasks: int = 50

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "noreply@agrovision.local"

    dzz_default_url: str = (
        "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer"
    )
    dzz_upstream: str = "https://www.dzz.by"
    dzz_sessions_path: str = "data/dzz-sessions.enc"
    dzz_session_ttl_hours: int = 8

    @field_validator("database_url")
    @classmethod
    def _ensure_async_driver(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def sync_database_url(self) -> str:
        if self.database_sync_url:
            return self.database_sync_url
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
