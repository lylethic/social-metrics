from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.legal import router as legal_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.redis import close_redis_pool, init_redis_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown events."""
    # Startup
    try:
        await init_redis_pool()
        print("[Startup] Redis connection pool initialized.")
    except Exception as e:
        print(f"[Startup Warning] Could not connect to Redis: {e}")

    yield

    # Shutdown
    await close_redis_pool()
    print("[Shutdown] Redis connection pool closed.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Microservice API for Social Media Insights Aggregation & AI Sentiment Analysis",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Set CORS middleware
if settings.BACKEND_CORS_ORIGINS:
    origins = [str(o).rstrip("/") for o in settings.BACKEND_CORS_ORIGINS]
    if settings.FRONTEND_URL and settings.FRONTEND_URL.rstrip("/") not in origins:
        origins.append(settings.FRONTEND_URL.rstrip("/"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if "*" not in origins else [],
        allow_origin_regex=r"^https?://.*" if "*" in origins else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health", tags=["Healthcheck"], status_code=status.HTTP_200_OK)
@app.get(f"{settings.API_V1_STR}/health", tags=["Healthcheck"], status_code=status.HTTP_200_OK)
async def health_check():
    """Service healthcheck endpoint."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "ai_provider": settings.AI_PROVIDER,
        "groq_model": settings.GROQ_MODEL,
    }


# Root-level Legal Endpoints (/terms and /privacy for OAuth compliance)
app.include_router(legal_router)

# Include API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)

