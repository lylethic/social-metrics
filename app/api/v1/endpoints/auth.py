from typing import Annotated
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, Token
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
)
async def register(
    user_in: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Create a new user account."""
    user = await auth_service.register(db, user_in)
    return user


@router.post(
    "/login",
    response_model=Token,
    summary="User login with JSON body",
)
async def login(
    login_in: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Authenticate with email and password to receive JWT tokens."""
    user = await auth_service.authenticate(db, login_in.email, login_in.password)
    return auth_service.generate_tokens(user)


@router.post(
    "/login/form",
    response_model=Token,
    summary="OAuth2 compatible token login for Swagger UI",
)
async def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Swagger UI authorization endpoint."""
    user = await auth_service.authenticate(db, form_data.username, form_data.password)
    return auth_service.generate_tokens(user)


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
)
async def refresh_token(
    refresh_in: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Exchange a valid refresh token for a new token pair."""
    return await auth_service.refresh_tokens(db, refresh_in.refresh_token)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Retrieve details of the currently logged-in user."""
    return current_user
