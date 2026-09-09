import os
from typing import List, Optional, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Social Media Insight Service"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Security & JWT
    SECRET_KEY: str = "b91d293845fecda913e71295b92750e32b8492048f0293da826194bc02816f12"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    # PostgreSQL Database
    POSTGRES_SERVER: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password"
    POSTGRES_DB: str = "social_insight"
    DATABASE_URL: Optional[str] = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info) -> str:
        if isinstance(v, str) and v.strip():
            return v
        # Fallback to building from individual postgres vars
        return (
            f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:"
            f"{os.getenv('POSTGRES_PASSWORD', 'postgres_password')}@"
            f"{os.getenv('POSTGRES_SERVER', 'db')}:{os.getenv('POSTGRES_PORT', 5432)}/"
            f"{os.getenv('POSTGRES_DB', 'social_insight')}"
        )

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # AI Engine (Groq)
    AI_PROVIDER: str = "groq"
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_URL: str = "https://api.groq.com/openai/v1"

    @field_validator("GROQ_URL", mode="before")
    @classmethod
    def sanitize_groq_url(cls, v: Optional[str]) -> str:
        if not v:
            return "https://api.groq.com/openai/v1"
        # If user entered /models at the end, clean it up to base url
        cleaned = v.rstrip("/")
        if cleaned.endswith("/models"):
            cleaned = cleaned[:-7]
        return cleaned

    # Platform API Credentials
    YOUTUBE_API_KEY: Optional[str] = None
    YOUTUBE_CLIENT_ID: Optional[str] = None
    YOUTUBE_CLIENT_SECRET: Optional[str] = None
    YOUTUBE_REDIRECT_URI: str = "http://127.0.0.1:5032/api/v1/platforms/youtube/callback"

    META_APP_ID: Optional[str] = None
    META_APP_SECRET: Optional[str] = None
    META_REDIRECT_URI: str = "http://127.0.0.1:5032/api/v1/platforms/meta/callback"


settings = Settings()
