"""API Endpoints for Social Platform Accounts and Connectors."""

import secrets
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.connectors.base import (
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorNotFoundError,
    ConnectorQuotaExceededError,
    ConnectorRateLimitError,
)
from app.connectors.youtube import YouTubeConnector
from app.core.database import get_db
from app.core.exceptions import (
    BadGatewayException,
    BadRequestException,
    NotFoundException,
    RateLimitException,
)
from app.models.user import User
from app.schemas.platform import (
    ConnectWithChannelIdRequest,
    FacebookConnectPageRequest,
    FacebookPageItem,
    InstagramConnectRequest,
    OAuthAuthorizeUrlResponse,
    OAuthCallbackRequest,
    PlatformAccountResponse,
    PlatformSyncResponse,
)
from app.services.account_service import account_service

router = APIRouter(prefix="/platforms", tags=["Platforms"])
youtube_connector = account_service.youtube_connector
facebook_connector = account_service.facebook_connector
instagram_connector = account_service.instagram_connector
threads_connector = account_service.threads_connector
meta_base = account_service.meta_base



@router.get("", response_model=List[PlatformAccountResponse], status_code=status.HTTP_200_OK)
async def list_platform_accounts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Filter by platform name: youtube, facebook, instagram"),
):
    """List all connected social platform accounts for the current user."""
    accounts = await account_service.list_by_user(db, current_user.id, platform=platform)
    return accounts


@router.get("/{account_id}", response_model=PlatformAccountResponse, status_code=status.HTTP_200_OK)
async def get_platform_account(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retrieve details of a connected platform account."""
    account = await account_service.get_by_id(db, account_id, user_id=current_user.id)
    if not account:
        raise NotFoundException(detail="Platform account not found.")
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform_account(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Disconnect and delete a social platform account."""
    await account_service.delete_account(db, account_id, user_id=current_user.id)
    await db.commit()
    return None


@router.get("/youtube/authorize", response_model=OAuthAuthorizeUrlResponse, status_code=status.HTTP_200_OK)
async def get_youtube_authorization_url(
    current_user: Annotated[User, Depends(get_current_user)],
    redirect_uri: Optional[str] = Query(None, description="Optional custom redirect URI"),
):
    """Generate YouTube OAuth2 authorization consent URL for connecting a channel."""
    state = f"user_{current_user.id}_{secrets.token_hex(16)}"
    try:
        auth_url = youtube_connector.get_authorization_url(state=state, redirect_uri=redirect_uri)
        return OAuthAuthorizeUrlResponse(
            platform="youtube",
            authorization_url=auth_url,
            state=state,
        )
    except ConnectorAuthError as exc:
        raise BadRequestException(detail=str(exc))


@router.post(
    "/youtube/callback",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Process YouTube OAuth callback code",
)
@router.post(
    "/connect/youtube",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=True,
    summary="Alternative endpoint to connect YouTube via OAuth code",
)
async def connect_youtube_oauth(
    payload: OAuthCallbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Process OAuth authorization code from YouTube/Google, exchange for tokens, and link channel."""
    try:
        # 1. Exchange authorization code for tokens
        tokens = await youtube_connector.authenticate(
            auth_code=payload.code,
            redirect_uri=payload.redirect_uri,
        )

        # 2. Fetch authenticated channel profile using the access token
        profile = await youtube_connector.get_channel_profile(
            account_id="mine",
            access_token=tokens.access_token,
        )

        # 3. Create or update PlatformAccount in DB
        account = await account_service.connect_or_update_account(
            db=db,
            user_id=current_user.id,
            profile=profile,
            tokens=tokens,
        )
        await db.commit()
        await db.refresh(account)
        return account

    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=f"YouTube authentication failed: {exc.message}")
    except ConnectorQuotaExceededError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"YouTube quota exceeded: {exc.message}")
    except ConnectorRateLimitError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"YouTube rate limit exceeded: {exc.message}")
    except ConnectorNotFoundError as exc:
        await db.rollback()
        raise NotFoundException(detail=f"YouTube channel not found: {exc.message}")
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=f"YouTube upstream error: {exc.message}")


@router.post("/youtube/connect-channel", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_youtube_channel_by_id(
    payload: ConnectWithChannelIdRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Connect a YouTube channel directly by Channel ID or Handle (using API Key)."""
    try:
        profile = await youtube_connector.get_channel_profile(account_id=payload.channel_id)
        account = await account_service.connect_or_update_account(
            db=db,
            user_id=current_user.id,
            profile=profile,
            tokens=None,
        )
        await db.commit()
        await db.refresh(account)
        return account

    except ConnectorNotFoundError as exc:
        await db.rollback()
        raise NotFoundException(detail=f"YouTube channel not found: {exc.message}")
    except ConnectorQuotaExceededError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"YouTube quota exceeded: {exc.message}")
    except ConnectorRateLimitError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"YouTube rate limit reached: {exc.message}")
    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=f"YouTube authentication error: {exc.message}")
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=f"YouTube upstream error: {exc.message}")


@router.post("/{account_id}/sync", response_model=PlatformSyncResponse, status_code=status.HTTP_200_OK)
async def sync_platform_account(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=50, description="Max number of recent posts to sync"),
):
    """Trigger an immediate sync of channel statistics and recent posts."""
    account = await account_service.get_by_id(db, account_id, user_id=current_user.id)
    if not account:
        raise NotFoundException(detail="Platform account not found.")

    try:
        sync_result = await account_service.sync_account_data(db, account, limit_posts=limit)
        await db.commit()
        return sync_result

    except ConnectorQuotaExceededError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"API quota exceeded: {exc.message}")
    except ConnectorRateLimitError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"Rate limit reached: {exc.message}")
    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=f"Authentication error with platform: {exc.message}")
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=f"Platform API error during sync: {exc.message}")


# -------------------------------------------------------------
# Facebook Graph API Endpoints
# -------------------------------------------------------------

@router.get("/facebook/authorize", response_model=OAuthAuthorizeUrlResponse, status_code=status.HTTP_200_OK)
async def get_facebook_authorization_url(
    current_user: Annotated[User, Depends(get_current_user)],
    redirect_uri: Optional[str] = Query(None, description="Optional custom redirect URI"),
):
    """Generate Meta OAuth consent URL for Facebook Pages and Insights."""
    state = f"user_{current_user.id}_{secrets.token_hex(16)}"
    try:
        auth_url = facebook_connector.get_authorization_url(state=state, redirect_uri=redirect_uri)
        return OAuthAuthorizeUrlResponse(
            platform="facebook",
            authorization_url=auth_url,
            state=state,
        )
    except ConnectorAuthError as exc:
        raise BadRequestException(detail=str(exc))


@router.post("/facebook/callback", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
@router.post("/connect/facebook", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_facebook_oauth(
    payload: OAuthCallbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Exchange Meta OAuth code, retrieve managed Facebook Pages, and connect the primary Page."""
    try:
        # 1. Exchange code for long-lived User Access Token
        tokens = await facebook_connector.authenticate(
            auth_code=payload.code,
            redirect_uri=payload.redirect_uri,
        )

        # 2. Get user's managed Facebook Pages
        pages = await meta_base.get_user_pages(tokens.access_token)
        if not pages:
            raise NotFoundException(detail="No managed Facebook Pages found for this user account.")

        # Connect the primary / first page
        primary_page = pages[0]
        page_id = str(primary_page["id"])
        page_access_token = primary_page.get("access_token") or tokens.access_token

        profile = await facebook_connector.get_channel_profile(
            account_id=page_id,
            access_token=page_access_token,
        )

        account = await account_service.connect_or_update_account(
            db=db,
            user_id=current_user.id,
            profile=profile,
            tokens=tokens,
        )
        # Store page access token directly in metadata or account token
        account.access_token = page_access_token
        await db.commit()
        await db.refresh(account)
        return account

    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=f"Facebook auth failed: {exc.message}")
    except ConnectorRateLimitError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"Facebook rate limit reached: {exc.message}")
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=f"Facebook upstream error: {exc.message}")


@router.get("/facebook/pages", response_model=List[FacebookPageItem], status_code=status.HTTP_200_OK)
async def list_user_facebook_pages(
    current_user: Annotated[User, Depends(get_current_user)],
    access_token: Optional[str] = Query(None, description="Optional User Access Token to fetch pages for"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """List all Facebook Pages managed by the user with linked Instagram accounts."""
    token = access_token
    if not token and db is not None:
        # Try finding existing connected Facebook or Instagram account token
        accounts = await account_service.list_by_user(db, current_user.id, platform="facebook")
        if accounts and accounts[0].access_token:
            token = accounts[0].access_token

    if not token:
        raise BadRequestException(detail="An active Meta access token is required to list Facebook Pages.")

    try:
        pages_data = await meta_base.get_user_pages(token)
        items: List[FacebookPageItem] = []
        for p in pages_data:
            ig_info = p.get("instagram_business_account")
            ig_id = ig_info.get("id") if isinstance(ig_info, dict) else None
            ig_user = ig_info.get("username") if isinstance(ig_info, dict) else None
            avatar = p.get("picture", {}).get("data", {}).get("url") if isinstance(p.get("picture"), dict) else None

            items.append(
                FacebookPageItem(
                    id=str(p["id"]),
                    name=p.get("name", "Unknown Page"),
                    category=p.get("category"),
                    avatar_url=avatar,
                    instagram_business_account_id=ig_id,
                    instagram_username=ig_user,
                )
            )
        return items
    except ConnectorAuthError as exc:
        raise BadRequestException(detail=str(exc))
    except ConnectorAPIError as exc:
        raise BadGatewayException(detail=str(exc))


@router.post("/facebook/connect-page", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_facebook_page_by_id(
    payload: FacebookConnectPageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Connect a specific Facebook Page by page_id."""
    token = payload.user_access_token
    if not token:
        accounts = await account_service.list_by_user(db, current_user.id, platform="facebook")
        if accounts and accounts[0].access_token:
            token = accounts[0].access_token

    if not token:
        raise BadRequestException(detail="An access token is required to connect a Facebook Page.")

    try:
        page_token = await meta_base.get_page_access_token(page_id=payload.page_id, user_access_token=token)
        profile = await facebook_connector.get_channel_profile(account_id=payload.page_id, access_token=page_token)

        account = await account_service.connect_or_update_account(
            db=db,
            user_id=current_user.id,
            profile=profile,
            tokens=None,
        )
        account.access_token = page_token
        await db.commit()
        await db.refresh(account)
        return account

    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=str(exc))
    except ConnectorNotFoundError as exc:
        await db.rollback()
        raise NotFoundException(detail=str(exc))
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=str(exc))


# -------------------------------------------------------------
# Instagram Graph API Endpoints
# -------------------------------------------------------------

@router.get("/instagram/authorize", response_model=OAuthAuthorizeUrlResponse, status_code=status.HTTP_200_OK)
async def get_instagram_authorization_url(
    current_user: Annotated[User, Depends(get_current_user)],
    redirect_uri: Optional[str] = Query(None, description="Optional custom redirect URI"),
):
    """Generate Meta OAuth consent URL for Instagram Business and Insights."""
    state = f"user_{current_user.id}_{secrets.token_hex(16)}"
    try:
        auth_url = instagram_connector.get_authorization_url(state=state, redirect_uri=redirect_uri)
        return OAuthAuthorizeUrlResponse(
            platform="instagram",
            authorization_url=auth_url,
            state=state,
        )
    except ConnectorAuthError as exc:
        raise BadRequestException(detail=str(exc))


@router.post("/instagram/callback", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
@router.post("/connect/instagram", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_instagram_oauth(
    payload: OAuthCallbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Exchange Meta OAuth code, discover linked Instagram Business Account, and connect it."""
    try:
        # 1. Exchange code for long-lived User Access Token
        tokens = await instagram_connector.authenticate(
            auth_code=payload.code,
            redirect_uri=payload.redirect_uri,
        )

        # 2. Find linked Instagram Business Accounts from user's pages
        pages = await meta_base.get_user_pages(tokens.access_token)
        ig_account_id = None
        page_access_token = tokens.access_token

        for p in pages:
            ig_info = p.get("instagram_business_account")
            if isinstance(ig_info, dict) and ig_info.get("id"):
                ig_account_id = str(ig_info["id"])
                page_access_token = p.get("access_token") or tokens.access_token
                break

        if not ig_account_id:
            raise NotFoundException(
                detail="No linked Instagram Business or Creator account found. Please link your Instagram account to a Facebook Page in Meta Business Suite."
            )

        # 3. Fetch Instagram profile
        profile = await instagram_connector.get_channel_profile(
            account_id=ig_account_id,
            access_token=page_access_token,
        )

        # 4. Save account
        account = await account_service.connect_or_update_account(
            db=db,
            user_id=current_user.id,
            profile=profile,
            tokens=tokens,
        )
        account.access_token = page_access_token
        await db.commit()
        await db.refresh(account)
        return account

    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=f"Instagram auth failed: {exc.message}")
    except ConnectorRateLimitError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"Instagram rate limit reached: {exc.message}")
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=f"Instagram upstream error: {exc.message}")


@router.post("/instagram/connect-account", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_instagram_account_by_id(
    payload: InstagramConnectRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Directly connect an Instagram Business Account by its ID and access token."""
    token = payload.user_access_token
    if not token:
        # Check if user has an existing Facebook/Instagram account to reuse token
        accounts = await account_service.list_by_user(db, current_user.id)
        for acc in accounts:
            if acc.platform in ("facebook", "instagram") and acc.access_token:
                token = acc.access_token
                break

    if not token:
        raise BadRequestException(detail="An access token is required to connect Instagram.")

    try:
        profile = await instagram_connector.get_channel_profile(
            account_id=payload.instagram_account_id,
            access_token=token,
        )
        account = await account_service.connect_or_update_account(
            db=db,
            user_id=current_user.id,
            profile=profile,
            tokens=None,
        )
        account.access_token = token
        await db.commit()
        await db.refresh(account)
        return account

    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=str(exc))
    except ConnectorNotFoundError as exc:
        await db.rollback()
        raise NotFoundException(detail=str(exc))
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=str(exc))


# -------------------------------------------------------------
# Official Threads API Endpoints
# -------------------------------------------------------------

@router.get("/threads/authorize", response_model=OAuthAuthorizeUrlResponse, status_code=status.HTTP_200_OK)
async def get_threads_authorization_url(
    current_user: Annotated[User, Depends(get_current_user)],
    redirect_uri: Optional[str] = Query(None, description="Optional custom redirect URI"),
):
    """Generate Official Threads OAuth2 consent URL."""
    state = f"user_{current_user.id}_{secrets.token_hex(16)}"
    try:
        auth_url = threads_connector.get_authorization_url(state=state, redirect_uri=redirect_uri)
        return OAuthAuthorizeUrlResponse(
            platform="threads",
            authorization_url=auth_url,
            state=state,
        )
    except ConnectorAuthError as exc:
        raise BadRequestException(detail=str(exc))


@router.post("/threads/callback", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
@router.post("/connect/threads", response_model=PlatformAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_threads_oauth(
    payload: OAuthCallbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Exchange Threads OAuth code, fetch profile, and connect Threads account."""
    try:
        # 1. Exchange code for long-lived Threads token (60 days)
        tokens = await threads_connector.authenticate(
            auth_code=payload.code,
            redirect_uri=payload.redirect_uri,
        )

        # 2. Fetch authenticated Threads profile
        profile = await threads_connector.get_channel_profile(
            account_id="me",
            access_token=tokens.access_token,
        )

        # 3. Create or update PlatformAccount in DB
        account = await account_service.connect_or_update_account(
            db=db,
            user_id=current_user.id,
            profile=profile,
            tokens=tokens,
        )
        await db.commit()
        await db.refresh(account)
        return account

    except ConnectorAuthError as exc:
        await db.rollback()
        raise BadRequestException(detail=f"Threads auth failed: {exc.message}")
    except ConnectorRateLimitError as exc:
        await db.rollback()
        raise RateLimitException(detail=f"Threads rate limit reached: {exc.message}")
    except ConnectorNotFoundError as exc:
        await db.rollback()
        raise NotFoundException(detail=f"Threads profile not found: {exc.message}")
    except ConnectorAPIError as exc:
        await db.rollback()
        raise BadGatewayException(detail=f"Threads upstream error: {exc.message}")
