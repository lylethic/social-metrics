from typing import Annotated, Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import (
    GoogleAuthUrlResponse,
    GoogleLoginRequest,
    LoginRequest,
    RefreshTokenRequest,
    Token,
)
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


# ─── Google OAuth Endpoints ───────────────────────────────────────────────────


@router.get(
    "/google/url",
    response_model=GoogleAuthUrlResponse,
    summary="Get Google OAuth authorization URL",
)
async def get_google_auth_url(
    state: Optional[str] = Query(None, description="Optional state parameter for CSRF protection"),
    redirect_uri: Optional[str] = Query(None, description="Optional custom redirect URI"),
) -> GoogleAuthUrlResponse:
    """Return the Google OAuth consent URL for frontend redirection."""
    url = auth_service.get_google_auth_url(state=state, redirect_uri=redirect_uri)
    return GoogleAuthUrlResponse(url=url)


@router.get(
    "/google/login",
    summary="Direct browser redirect to Google OAuth login screen",
    response_class=RedirectResponse,
)
async def google_login_redirect(
    state: Optional[str] = Query(None, description="Optional state parameter"),
    redirect_uri: Optional[str] = Query(None, description="Optional custom redirect URI"),
) -> RedirectResponse:
    """Directly redirect the browser to Google's consent screen."""
    url = auth_service.get_google_auth_url(state=state, redirect_uri=redirect_uri)
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/google/callback",
    summary="Handle Google OAuth redirect callback",
    response_class=RedirectResponse,
)
async def google_oauth_callback(
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Optional[str] = Query(None, description="Authorization code from Google"),
    state: Optional[str] = Query(None, description="State param returned from Google"),
    error: Optional[str] = Query(None, description="OAuth error if user denied consent"),
    error_description: Optional[str] = Query(None, description="Description of OAuth error"),
) -> RedirectResponse:
    """Process Google OAuth redirect callback.

    Exchanges authorization code for Google profile, finds or registers the user,
    issues JWT tokens, and redirects back to the frontend application.
    """
    frontend_login_url = f"{settings.FRONTEND_URL.rstrip('/')}/login"

    if error:
        err_msg = error_description or error
        return RedirectResponse(
            url=f"{frontend_login_url}?error={quote(f'Google OAuth error: {err_msg}')}",
            status_code=status.HTTP_302_FOUND,
        )

    if not code:
        return RedirectResponse(
            url=f"{frontend_login_url}?error={quote('Missing authorization code from Google.')}",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        user, tokens = await auth_service.login_or_register_with_google(
            db=db,
            code=code,
            redirect_uri=settings.effective_google_redirect_uri,
        )
        callback_target = (
            f"{settings.FRONTEND_URL.rstrip('/')}/auth/callback"
            f"?access_token={tokens.access_token}&refresh_token={tokens.refresh_token}"
        )
        return RedirectResponse(url=callback_target, status_code=status.HTTP_302_FOUND)
    except Exception as exc:
        return RedirectResponse(
            url=f"{frontend_login_url}?error={quote(str(exc))}",
            status_code=status.HTTP_302_FOUND,
        )


@router.post(
    "/google",
    response_model=Token,
    summary="Authenticate with Google code or ID token via JSON body",
)
async def google_login_json(
    body: GoogleLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Authenticate or register a user by sending a Google code or ID token via JSON body."""
    _, tokens = await auth_service.login_or_register_with_google(
        db=db,
        code=body.code,
        id_token_str=body.id_token,
        redirect_uri=body.redirect_uri,
    )
    return tokens
