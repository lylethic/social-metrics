from typing import Optional
import redis.asyncio as aioredis
from app.core.config import settings

redis_client: Optional[aioredis.Redis] = None


async def init_redis_pool() -> aioredis.Redis:
    """Initialize Redis connection pool."""
    global redis_client
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    return redis_client


async def close_redis_pool() -> None:
    """Close Redis connection pool."""
    global redis_client
    if redis_client is not None:
        await redis_client.close()


async def get_redis() -> aioredis.Redis:
    """Dependency for getting async Redis client."""
    global redis_client
    if redis_client is None:
        await init_redis_pool()
    return redis_client
