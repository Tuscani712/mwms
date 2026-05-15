"""Application settings (loaded from environment / .env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WMS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    secret_key: str = "dev-only-secret-key-do-not-use-in-prod"
    db_url: str = "sqlite:///./data/wms.db"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:8765,http://127.0.0.1:8765"
    site_id_default: str = "WHS-001"
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 2 * 1024 * 1024
    max_image_dimension: int = 2048

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
