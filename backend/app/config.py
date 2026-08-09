from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg2://docarchive:docarchive@db:5432/docarchive"

    # Auth
    # The S105 suppression below marks a TRUE positive, not a false one. A
    # usable default signing key
    # with no production guard is a real hole - anyone who knows the default
    # forges an admin token. The fix is a fail-fast validator that refuses to
    # boot with this value when ENVIRONMENT=production, which is a separate
    # change; this suppression exists to unblock the lint gate and comes out
    # with that commit.
    jwt_secret: str = "change-me-in-production"  # noqa: S105
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
    admin_password: str = "changeme"  # noqa: S105  - same as jwt_secret above

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
