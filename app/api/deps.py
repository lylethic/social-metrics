import uuid
from typing import Annotated
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_token
from app.models.user import User
from app.services.auth_service import auth_service

http_bearer = HTTPBearer(
    description="Enter access_token (without 'Bearer ' prefix, Swagger UI adds it automatically)",
    auto_error=True,
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency to retrieve the currently authenticated user from Bearer JWT."""
    token = credentials.credentials
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise UnauthorizedException(detail="Invalid token type.")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedException(detail="Could not validate credentials.")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedException(detail="Invalid user ID format.")

    user = await auth_service.get_by_id(db, user_id)
    if not user:
        raise UnauthorizedException(detail="User not found.")
    if not user.is_active:
        raise UnauthorizedException(detail="Inactive user.")

    return user


async def get_current_active_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency for admin-only routes."""
    if not current_user.is_superuser and current_user.role != "admin":
        raise ForbiddenException(detail="Insufficient privileges.")
    return current_user
