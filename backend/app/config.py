from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg2://docarchive:docarchive@db:5432/docarchive"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12  # 12h

    # File storage
    storage_dir: str = "/data/files"
    # Fernet key (urlsafe base64, 32 bytes). Generate: Fernet.generate_key()
    file_encryption_key: str = ""

    # Uploads
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MB
    allowed_mime_types: tuple[str, ...] = (
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
    )

    # OCR
    ocr_languages: str = "ita"
    pdf_dpi: int = 200

    # CORS — frontend origin(s), comma-separated
    cors_origins: str = "http://localhost:5173"

    # First admin bootstrap (used by seed script)
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
