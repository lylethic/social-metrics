import uuid
from datetime import timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestException, ConflictException, UnauthorizedException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.user import UserCreate


class AuthService:
    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> Optional[User]:
        """Fetch user by email."""
        result = await db.execute(select(User).where(User.email == email))
        return result.scalars().first()

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
        """Fetch user by UUID id."""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

    @staticmethod
    async def register(db: AsyncSession, user_in: UserCreate) -> User:
        """Register a new user."""
        existing = await AuthService.get_by_email(db, user_in.email)
        if existing:
            raise ConflictException(detail="An account with this email already exists.")

        user = User(
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password),
            full_name=user_in.full_name,
            is_active=True,
            is_superuser=False,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    @staticmethod
    async def authenticate(db: AsyncSession, email: str, password: str) -> User:
        """Authenticate user by email and password."""
        user = await AuthService.get_by_email(db, email)
        if not user:
            raise UnauthorizedException(detail="Incorrect email or password.")
        if not verify_password(password, user.hashed_password):
            raise UnauthorizedException(detail="Incorrect email or password.")
        if not user.is_active:
            raise BadRequestException(detail="Inactive user account.")
        return user

    @staticmethod
    def generate_tokens(user: User) -> Token:
        """Generate JWT access & refresh token pair."""
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            subject=str(user.id),
            expires_delta=access_token_expires,
            extra_claims={"email": user.email, "role": user.role},
        )
        refresh_token = create_refresh_token(subject=str(user.id))

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    async def refresh_tokens(db: AsyncSession, refresh_token: str) -> Token:
        """Verify refresh token and issue new token pair."""
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedException(detail="Invalid token type.")

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise UnauthorizedException(detail="Invalid token payload.")

        try:
            user_id = uuid.UUID(user_id_str)
        except ValueError:
            raise UnauthorizedException(detail="Invalid user ID format.")

        user = await AuthService.get_by_id(db, user_id)
        if not user or not user.is_active:
            raise UnauthorizedException(detail="User not found or inactive.")

        return AuthService.generate_tokens(user)


auth_service = AuthService()
