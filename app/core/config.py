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
    NGROK_BACKEND_URL: Optional[str] = None

    # Security & JWT
    SECRET_KEY: Optional[str] = None
    ALGORITHM: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    REFRESH_TOKEN_EXPIRE_DAYS: Optional[int] = None
    TOKEN_ENCRYPTION_KEY: Optional[str] = None  # Fernet key for encrypting OAuth tokens

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "*",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://either-negative-botanist.ngrok-free.dev",
    ]

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

    # Google / YouTube endpoint URLs (overridable for testing or proxy setups)
    GOOGLE_AUTH_BASE_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL: str = "https://www.googleapis.com/oauth2/v3/userinfo"
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None
    YOUTUBE_API_BASE_URL: str = "https://www.googleapis.com/youtube/v3"

    @property
    def effective_google_client_id(self) -> Optional[str]:
        return self.GOOGLE_CLIENT_ID or self.YOUTUBE_CLIENT_ID

    @property
    def effective_google_client_secret(self) -> Optional[str]:
        return self.GOOGLE_CLIENT_SECRET or self.YOUTUBE_CLIENT_SECRET

    @property
    def effective_google_redirect_uri(self) -> str:
        if self.GOOGLE_REDIRECT_URI:
            return self.GOOGLE_REDIRECT_URI
        if self.NGROK_BACKEND_URL:
            return f"{self.NGROK_BACKEND_URL.rstrip('/')}/api/v1/auth/google/callback"
        return "http://127.0.0.1:5032/api/v1/auth/google/callback"

    META_APP_ID: Optional[str] = None
    META_APP_SECRET: Optional[str] = None
    META_REDIRECT_URI: str = "http://127.0.0.1:5032/api/v1/platforms/facebook/callback"
    META_API_VERSION: str = "v20.0"

    THREADS_APP_ID: Optional[str] = None
    THREADS_APP_SECRET: Optional[str] = None
    THREADS_REDIRECT_URI: str = "http://127.0.0.1:5032/api/v1/platforms/threads/callback"

    # TikTok API Credentials
    TIKTOK_CLIENT_KEY: Optional[str] = None
    TIKTOK_CLIENT_SECRET: Optional[str] = None
    TIKTOK_REDIRECT_URI: str = "http://127.0.0.1:5032/api/v1/platforms/tiktok/callback"
    TIKTOK_AUTH_BASE_URL: str = "https://www.tiktok.com/v2/auth/authorize/"
    TIKTOK_TOKEN_URL: str = "https://open.tiktokapis.com/v2/oauth/token/"
    TIKTOK_API_BASE_URL: str = "https://open.tiktokapis.com/v2"
    TIKTOK_WEBHOOK_SECRET: Optional[str] = None

    # Frontend Application URL for OAuth redirects
    FRONTEND_URL: str = "http://localhost:3000"



settings = Settings()
