import logging
import secrets
import uuid
from datetime import timedelta
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx
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

logger = logging.getLogger(__name__)


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

    @staticmethod
    def get_google_auth_url(state: Optional[str] = None, redirect_uri: Optional[str] = None) -> str:
        """Generate Google OAuth consent URL for user login/registration."""
        client_id = settings.effective_google_client_id
        if not client_id:
            raise BadRequestException(detail="Google client ID is not configured on the server.")

        resolved_redirect_uri = redirect_uri or settings.effective_google_redirect_uri
        params = {
            "client_id": client_id,
            "redirect_uri": resolved_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
        }
        if state:
            params["state"] = state

        return f"{settings.GOOGLE_AUTH_BASE_URL}?{urlencode(params)}"

    @staticmethod
    async def login_or_register_with_google(
        db: AsyncSession,
        code: Optional[str] = None,
        id_token_str: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[User, Token]:
        """Authenticate or auto-register a user using Google OAuth credentials."""
        client_id = settings.effective_google_client_id
        client_secret = settings.effective_google_client_secret

        if not client_id:
            raise BadRequestException(detail="Google client ID is not configured on the server.")

        email: Optional[str] = None
        full_name: Optional[str] = None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if code:
                    if not client_secret:
                        raise BadRequestException(detail="Google client secret is not configured on the server.")

                    resolved_redirect_uri = redirect_uri or settings.effective_google_redirect_uri
                    token_payload = {
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": resolved_redirect_uri,
                        "grant_type": "authorization_code",
                    }
                    token_resp = await client.post(settings.GOOGLE_TOKEN_URL, data=token_payload)
                    token_data = token_resp.json()

                    if token_resp.status_code != 200:
                        err_msg = (
                            token_data.get("error_description")
                            or token_data.get("error")
                            or "Failed to exchange Google code"
                        )
                        logger.error(f"[Google Auth] Token exchange failed: {err_msg}")
                        raise UnauthorizedException(detail=f"Google authentication failed: {err_msg}")

                    google_access_token = token_data.get("access_token")
                    userinfo_resp = await client.get(
                        settings.GOOGLE_USERINFO_URL,
                        headers={"Authorization": f"Bearer {google_access_token}"},
                    )
                    if userinfo_resp.status_code != 200:
                        logger.error(f"[Google Auth] Failed to fetch userinfo: {userinfo_resp.text}")
                        raise UnauthorizedException(detail="Failed to retrieve profile info from Google.")

                    user_info = userinfo_resp.json()
                    email = user_info.get("email")
                    full_name = user_info.get("name")
                elif id_token_str:
                    verify_resp = await client.get(
                        f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token_str}"
                    )
                    if verify_resp.status_code != 200:
                        raise UnauthorizedException(detail="Invalid Google ID token.")
                    user_info = verify_resp.json()
                    email = user_info.get("email")
                    full_name = user_info.get("name")
                else:
                    raise BadRequestException(detail="Either authorization code or ID token must be provided.")
        except httpx.RequestError as exc:
            logger.error(f"[Google Auth] Network error during Google auth: {exc}")
            raise UnauthorizedException(detail="Network error communicating with Google servers.")

        if not email:
            raise UnauthorizedException(detail="Unable to obtain verified email address from Google.")

        # Check existing user
        user = await AuthService.get_by_email(db, email)
        if user:
            if not user.is_active:
                raise UnauthorizedException(detail="User account is inactive. Please contact support.")
            if not user.full_name and full_name:
                user.full_name = full_name
                db.add(user)
                await db.flush()
                await db.refresh(user)
        else:
            # Auto-register new user via Google
            random_pw = secrets.token_urlsafe(32)
            user = User(
                email=email,
                hashed_password=get_password_hash(random_pw),
                full_name=full_name,
                is_active=True,
                is_superuser=False,
            )
            db.add(user)
            await db.flush()
            await db.refresh(user)
            logger.info(f"[Google Auth] Created new user from Google OAuth: {email}")

        tokens = AuthService.generate_tokens(user)
        return user, tokens


auth_service = AuthService()
