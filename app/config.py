from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NUNI Repository"
    app_env: str = "development"
    secret_key: str = "change-this-in-production"
    database_url: str = "sqlite:///./data/nuni_repository.db"

    admin_username: str = "admin"
    admin_password: str = "admin"
    admin_display_name: str = "admin"

    storage_type: str = "local"
    local_storage_path: str = "./data/repository"
    webdav_url: str = "http://127.0.0.1:8085/dav"
    webdav_username: str = "test"
    webdav_password: str = "test"
    webdav_verify_ssl: bool = True
    webdav_timeout_seconds: float = 30.0

    show_env_badge: bool = True
    max_upload_mb: int = 2048

    @property
    def is_local(self) -> bool:
        return self.storage_type.lower() == "local"

    @property
    def storage_label(self) -> str:
        if self.is_local:
            return f"LOCAL · {Path(self.local_storage_path).resolve()}"
        return f"WEBDAV · {self.webdav_url}"


settings = Settings()
