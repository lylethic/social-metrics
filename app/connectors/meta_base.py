"""Meta (Facebook & Instagram) Base Connector and Token Lifecycle Management.

Handles OAuth dialog URL generation, code-to-token exchange, short-lived to 60-day
long-lived token exchange, Facebook Pages retrieval, and Graph API request resilience.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from app.connectors.base import (
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    OAuthTokenResponse,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class MetaBaseConnector:
    """Base client for Meta Graph API v20.0+ authentication and shared utilities."""

    DEFAULT_API_VERSION: str = "v20.0"
    OAUTH_DIALOG_URL: str = "https://www.facebook.com/{version}/dialog/oauth"
    GRAPH_API_BASE_URL: str = "https://graph.facebook.com/{version}"

    DEFAULT_SCOPES: List[str] = [
        "pages_show_list",
        "pages_read_engagement",
        "pages_read_user_content",
        "read_insights",
        "instagram_basic",
        "instagram_manage_insights",
        "public_profile",
    ]

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        api_version: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        self.app_id = app_id or settings.META_APP_ID
        self.app_secret = app_secret or settings.META_APP_SECRET
        self.redirect_uri = redirect_uri or settings.META_REDIRECT_URI
        self.api_version = api_version or getattr(settings, "META_API_VERSION", self.DEFAULT_API_VERSION)
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    @property
    def base_url(self) -> str:
        """Construct base URL for current Graph API version."""
        return self.GRAPH_API_BASE_URL.format(version=self.api_version)

    def get_authorization_url(
        self,
        state: str,
        redirect_uri: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> str:
        """Generate Meta OAuth2 consent URL for requesting Page and Instagram permissions."""
        if not self.app_id:
            raise ConnectorAuthError(
                "Meta app_id is not configured",
                platform="meta",
            )

        requested_scopes = scopes or self.DEFAULT_SCOPES
        dialog_url = self.OAUTH_DIALOG_URL.format(version=self.api_version)
        params = {
            "client_id": self.app_id,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": ",".join(requested_scopes),
        }
        return f"{dialog_url}?{urlencode(params)}"

    async def exchange_code_for_short_lived_token(
        self,
        auth_code: str,
        redirect_uri: Optional[str] = None,
    ) -> OAuthTokenResponse:
        """Exchange OAuth code for a short-lived (1-2 hours) User Access Token."""
        if not self.app_id or not self.app_secret:
            raise ConnectorAuthError(
                "Meta app_id or app_secret is not configured",
                platform="meta",
            )

        endpoint = f"{self.base_url}/oauth/access_token"
        params = {
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "code": auth_code,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(endpoint, params=params)
                data = response.json()

                if response.status_code != 200 or "error" in data:
                    error_msg = self._extract_error_message(data)
                    raise ConnectorAuthError(
                        f"Meta OAuth code exchange failed ({response.status_code}): {error_msg}",
                        platform="meta",
                    )

                return OAuthTokenResponse(
                    access_token=data["access_token"],
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in"),  # Typically ~3600-7200 seconds
                    raw_response=data,
                )
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error during Meta OAuth code exchange: {str(exc)}",
                platform="meta",
                original_error=exc,
            )

    async def exchange_for_long_lived_token(
        self,
        short_lived_token: str,
    ) -> OAuthTokenResponse:
        """Exchange a short-lived User Token for a 60-day Long-lived User Token."""
        if not self.app_id or not self.app_secret:
            raise ConnectorAuthError(
                "Meta app_id or app_secret is not configured",
                platform="meta",
            )

        endpoint = f"{self.base_url}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "fb_exchange_token": short_lived_token,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(endpoint, params=params)
                data = response.json()

                if response.status_code != 200 or "error" in data:
                    error_msg = self._extract_error_message(data)
                    raise ConnectorAuthError(
                        f"Meta long-lived token exchange failed ({response.status_code}): {error_msg}",
                        platform="meta",
                    )

                # Long-lived token typically expires in ~5184000 seconds (60 days)
                return OAuthTokenResponse(
                    access_token=data["access_token"],
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in", 60 * 24 * 3600),
                    raw_response=data,
                )
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error during Meta long-lived token exchange: {str(exc)}",
                platform="meta",
                original_error=exc,
            )

    async def get_user_pages(self, user_access_token: str) -> List[Dict[str, Any]]:
        """Fetch all Facebook Pages managed by the user with Page Access Tokens and linked IG accounts.

        When called with a long-lived user token, the returned page access tokens do not expire
        unless revoked or user password changes.
        """
        data = await self.make_graph_request(
            endpoint="/me/accounts",
            params={
                "fields": "id,name,category,access_token,tasks,picture{url},instagram_business_account{id,username,name,profile_picture_url,followers_count,media_count}"
            },
            access_token=user_access_token,
        )
        return data.get("data", [])

    async def get_page_access_token(self, page_id: str, user_access_token: str) -> str:
        """Fetch the specific Page Access Token for a given page_id."""
        pages = await self.get_user_pages(user_access_token=user_access_token)
        for p in pages:
            if p.get("id") == str(page_id):
                page_token = p.get("access_token")
                if page_token:
                    return page_token
                break

        # Fallback: query page node directly
        data = await self.make_graph_request(
            endpoint=f"/{page_id}",
            params={"fields": "access_token"},
            access_token=user_access_token,
        )
        token = data.get("access_token")
        if not token:
            raise ConnectorAuthError(
                f"Could not obtain page access token for Facebook Page {page_id}",
                platform="facebook",
            )
        return token

    async def make_graph_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        access_token: Optional[str] = None,
        method: str = "GET",
        json_body: Optional[Dict[str, Any]] = None,
        platform_name: str = "meta",
    ) -> Dict[str, Any]:
        """Execute HTTP request to Meta Graph API with exponential backoff and error classification."""
        cleaned_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.base_url}{cleaned_endpoint}"
        query_params = dict(params or {})

        headers = {
            "Accept": "application/json",
        }

        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    if method.upper() == "POST":
                        response = await client.post(url, params=query_params, json=json_body, headers=headers)
                    else:
                        response = await client.get(url, params=query_params, headers=headers)

                    status = response.status_code

                    # Check for rate limit or transient errors eligible for retry
                    if status in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries:
                            delay = self.backoff_factor * (2 ** attempt)
                            retry_after = response.headers.get("Retry-After")
                            if retry_after and retry_after.isdigit():
                                delay = max(delay, float(retry_after))
                            logger.warning(
                                f"Meta Graph API returned {status}. Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            if status == 429:
                                raise ConnectorRateLimitError(
                                    f"Meta Graph API rate limit exceeded after {self.max_retries} retries",
                                    platform=platform_name,
                                )
                            raise ConnectorAPIError(
                                f"Meta Graph API server error: HTTP {status}",
                                platform=platform_name,
                                status_code=status,
                            )

                    try:
                        data = response.json()
                    except Exception:
                        response.raise_for_status()
                        return {}

                    # Inspect Meta error structure
                    if "error" in data:
                        self._handle_graph_api_error(data["error"], status, platform_name)

                    if status >= 400:
                        raise ConnectorAPIError(
                            f"Meta Graph API returned error {status}: {response.text}",
                            platform=platform_name,
                            status_code=status,
                            raw_response=data if isinstance(data, dict) else None,
                        )

                    return data

            except (ConnectorAuthError, ConnectorRateLimitError, ConnectorNotFoundError, ConnectorAPIError):
                raise
            except httpx.RequestError as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = self.backoff_factor * (2 ** attempt)
                    logger.warning(
                        f"Network error connecting to Meta Graph API ({exc}). Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    raise ConnectorAPIError(
                        f"Network failure connecting to Meta Graph API: {str(exc)}",
                        platform=platform_name,
                        original_error=exc,
                    )

        if last_exception:
            raise ConnectorAPIError(
                f"Meta request failed: {str(last_exception)}",
                platform=platform_name,
                original_error=last_exception,
            )

        return {}

    def _handle_graph_api_error(self, error: Dict[str, Any], http_status: int, platform_name: str) -> None:
        """Classify Meta Graph API error codes into specific domain exceptions."""
        code = error.get("code")
        subcode = error.get("error_subcode")
        message = error.get("message", "Unknown Meta Graph API error")
        error_type = error.get("type", "")

        # Code 190: Invalid or expired OAuth access token
        # Code 102: API Session error
        if code in (190, 102) or (error_type == "OAuthException" and "session" in message.lower()):
            raise ConnectorAuthError(
                f"Meta token invalid or expired: {message} (code: {code}, subcode: {subcode})",
                platform=platform_name,
            )

        # Rate limits: Code 4 (App limit), 17 (User limit), 32 (Page limit), 613 (Calls limit)
        if code in (4, 17, 32, 613) or "rate limit" in message.lower() or "request limit" in message.lower():
            raise ConnectorRateLimitError(
                f"Meta rate limit reached: {message} (code: {code})",
                platform=platform_name,
            )

        # Object Not Found: Code 100 with not exist, Code 803 (some page/user alias not found)
        if code == 803 or (code == 100 and ("does not exist" in message or "cannot be accessed" in message or "not found" in message)):
            raise ConnectorNotFoundError(
                f"Meta resource not found: {message} (code: {code})",
                platform=platform_name,
            )

        # Permission denied
        if code in (10, 200, 298) or "permission" in message.lower():
            raise ConnectorAuthError(
                f"Insufficient Meta permissions: {message} (code: {code})",
                platform=platform_name,
            )

        raise ConnectorAPIError(
            f"Meta Graph API error ({code}): {message}",
            platform=platform_name,
            status_code=http_status,
            raw_response={"error": error},
        )

    def _extract_error_message(self, data: Dict[str, Any]) -> str:
        """Helper to extract clean error message string from response."""
        if "error" in data:
            err = data["error"]
            if isinstance(err, dict):
                return err.get("message") or str(err)
            return str(err)
        return data.get("error_description") or str(data)
