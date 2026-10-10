import os

API_PREFIX = "/api/v1"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./wefit.db"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def to_async_url(url: str) -> str:
    # SQLAlchemy needs an async driver; accept plain Postgres URLs for convenience.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


def get_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
