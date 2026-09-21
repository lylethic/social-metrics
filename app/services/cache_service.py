"""Redis caching layer for dashboard analytics and insights."""

import json
import logging
import uuid
from typing import Any, Optional, Union

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

# Default Cache TTL for insights summary: 15 minutes (900 seconds)
INSIGHTS_CACHE_TTL = 900


class CacheService:
    """Service providing asynchronous Redis caching with graceful error recovery."""

    @staticmethod
    def build_insights_key(user_id: Union[uuid.UUID, str], platform: Optional[str] = None) -> str:
        """Construct standard cache key for user's insights summary."""
        plat = platform.strip().lower() if platform else "all"
        return f"insights:summary:{str(user_id)}:{plat}"

    async def get(self, key: str) -> Optional[Any]:
        """Fetch and deserialize JSON value from Redis by key. Returns None if not found or on error."""
        try:
            client = await get_redis()
            data = await client.get(key)
            if data is not None:
                return json.loads(data)
        except Exception as exc:
            logger.warning(f"[CacheService] Redis GET error for key '{key}': {exc}")
        return None

    async def set(self, key: str, value: Any, ttl: int = INSIGHTS_CACHE_TTL) -> bool:
        """Serialize and set a key with TTL in Redis. Returns True on success, False on error."""
        try:
            client = await get_redis()
            payload = json.dumps(value, default=str)
            await client.setex(key, ttl, payload)
            return True
        except Exception as exc:
            logger.warning(f"[CacheService] Redis SET error for key '{key}': {exc}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a single key from Redis."""
        try:
            client = await get_redis()
            await client.delete(key)
            return True
        except Exception as exc:
            logger.warning(f"[CacheService] Redis DELETE error for key '{key}': {exc}")
            return False

    async def invalidate_user_insights(self, user_id: Union[uuid.UUID, str]) -> int:
        """
        Invalidate all cached insight summaries for a specific user.
        Uses SCAN to find keys matching 'insights:*:user_id*' and deletes them.
        """
        deleted_count = 0
        try:
            client = await get_redis()
            pattern = f"insights:*:{str(user_id)}*"
            keys_to_delete = []
            
            # Use scan_iter for non-blocking key iteration
            async for matched_key in client.scan_iter(match=pattern):
                keys_to_delete.append(matched_key)

            if keys_to_delete:
                deleted_count = await client.delete(*keys_to_delete)
                logger.info(f"[CacheService] Invalidated {deleted_count} cache keys for user {user_id}")
        except Exception as exc:
            logger.warning(f"[CacheService] Redis invalidation error for user {user_id}: {exc}")
        return deleted_count


cache_service = CacheService()
