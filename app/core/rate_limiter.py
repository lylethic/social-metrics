"""Redis-backed Rate Limiter dependency for FastAPI endpoints."""

import logging
import time
from typing import Callable, Optional

from fastapi import Request
from starlette import status

from app.core.exceptions import RateLimitException
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def rate_limiter(
    times: int = 60,
    seconds: int = 60,
    scope: Optional[str] = None,
) -> Callable:
    """
    Factory creating a FastAPI dependency that enforces Redis sliding-window / fixed-window rate limiting.

    :param times: Maximum number of allowed requests.
    :param seconds: Time window in seconds.
    :param scope: Optional scope identifier for this limiter.
    """
    async def _dependency(request: Request) -> None:
        # Determine client identifier: authenticated user sub/id if available, else IP
        user_id = getattr(request.state, "user_id", None)
        if not user_id and "user" in request.scope:
            user_id = getattr(request.scope["user"], "id", None)

        if not user_id:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_id = forwarded.split(",")[0].strip()
            else:
                client_id = request.client.host if request.client else "127.0.0.1"
        else:
            client_id = str(user_id)

        endpoint_scope = scope or request.url.path
        window_bucket = int(time.time() // seconds)
        cache_key = f"rate_limit:{endpoint_scope}:{client_id}:{window_bucket}"

        try:
            client = await get_redis()
            current_count = await client.incr(cache_key)

            if current_count == 1:
                # Set expiration for the bucket
                await client.expire(cache_key, seconds + 2)

            if current_count > times:
                ttl = await client.ttl(cache_key)
                retry_after = max(ttl, 1)
                logger.warning(
                    f"[RateLimiter] Rate limit exceeded for {client_id} on {endpoint_scope}: "
                    f"{current_count}/{times} requests. Retry after {retry_after}s."
                )
                raise RateLimitException(
                    detail=f"Rate limit exceeded. Maximum {times} requests per {seconds}s allowed."
                )

        except RateLimitException:
            raise
        except Exception as exc:
            # Graceful degradation: allow request if Redis fails
            logger.warning(f"[RateLimiter] Redis error during rate limit check: {exc}")

    return _dependency
