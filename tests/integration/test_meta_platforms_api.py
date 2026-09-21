"""Integration tests for Meta (Facebook, Instagram) and Threads API endpoints."""

import pytest
import respx
import httpx
from httpx import AsyncClient

from app.core.config import settings


@pytest.fixture
def auth_headers(client: AsyncClient):
    """Fixture returning helper to register and log in a user."""
    async def _get_headers(email: str = "metauser@example.com", password: str = "password123"):
        # Register
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Meta Test User"},
        )
        # Login
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        token = login_res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _get_headers


@pytest.fixture(autouse=True)
def mock_meta_credentials():
    """Ensure Meta and Threads app credentials exist during tests."""
    from app.api.v1.endpoints.platforms import (
        facebook_connector,
        instagram_connector,
        meta_base,
        threads_connector,
    )
    from app.services.account_service import account_service

    orig_meta_id = settings.META_APP_ID
    orig_meta_secret = settings.META_APP_SECRET
    orig_threads_id = settings.THREADS_APP_ID
    orig_threads_secret = settings.THREADS_APP_SECRET

    settings.META_APP_ID = "mock-meta-app-id"
    settings.META_APP_SECRET = "mock-meta-app-secret"
    settings.THREADS_APP_ID = "mock-threads-app-id"
    settings.THREADS_APP_SECRET = "mock-threads-app-secret"

    for conn in (facebook_connector, instagram_connector, account_service.facebook_connector, account_service.instagram_connector):
        conn.app_id = "mock-meta-app-id"
        conn.app_secret = "mock-meta-app-secret"
        conn.meta_base.app_id = "mock-meta-app-id"
        conn.meta_base.app_secret = "mock-meta-app-secret"

    meta_base.app_id = "mock-meta-app-id"
    meta_base.app_secret = "mock-meta-app-secret"
    account_service.meta_base.app_id = "mock-meta-app-id"
    account_service.meta_base.app_secret = "mock-meta-app-secret"

    threads_connector.app_id = "mock-threads-app-id"
    threads_connector.app_secret = "mock-threads-app-secret"
    account_service.threads_connector.app_id = "mock-threads-app-id"
    account_service.threads_connector.app_secret = "mock-threads-app-secret"

    yield

    settings.META_APP_ID = orig_meta_id
    settings.META_APP_SECRET = orig_meta_secret
    settings.THREADS_APP_ID = orig_threads_id
    settings.THREADS_APP_SECRET = orig_threads_secret


@pytest.mark.asyncio
async def test_get_facebook_and_instagram_authorize_urls(client: AsyncClient, auth_headers):
    """Test getting Facebook and Instagram OAuth consent URLs."""
    headers = await auth_headers(email="authurls@example.com")

    # Facebook
    fb_res = await client.get("/api/v1/platforms/facebook/authorize", headers=headers)
    assert fb_res.status_code == 200
    fb_data = fb_res.json()
    assert fb_data["platform"] == "facebook"
    assert "dialog/oauth" in fb_data["authorization_url"]
    assert "client_id=mock-meta-app-id" in fb_data["authorization_url"]

    # Instagram
    ig_res = await client.get("/api/v1/platforms/instagram/authorize", headers=headers)
    assert ig_res.status_code == 200
    ig_data = ig_res.json()
    assert ig_data["platform"] == "instagram"
    assert "instagram_basic" in ig_data["authorization_url"]



@pytest.mark.asyncio
@respx.mock
async def test_facebook_oauth_callback_and_crud(client: AsyncClient, auth_headers):
    """Test Facebook OAuth callback connecting a page, listing it, and syncing."""
    headers = await auth_headers(email="fbtest@example.com")

    # 1. Mock token exchange
    respx.get("https://graph.facebook.com/v20.0/oauth/access_token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "fb_short_tok", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "fb_long_tok", "expires_in": 5184000}),
        ]
    )

    # 2. Mock /me/accounts (pages)
    mock_pages = {
        "data": [
            {
                "id": "11223344",
                "name": "My Tech Brand",
                "category": "Brand",
                "access_token": "page_token_11223344",
                "picture": {"data": {"url": "https://example.com/brand.jpg"}},
            }
        ]
    }
    respx.get("https://graph.facebook.com/v20.0/me/accounts").mock(
        return_value=httpx.Response(200, json=mock_pages)
    )

    # 3. Mock page profile and insights
    mock_page_profile = {
        "id": "11223344",
        "name": "My Tech Brand",
        "username": "mytechbrand",
        "fan_count": 25000,
        "followers_count": 27000,
        "picture": {"data": {"url": "https://example.com/brand.jpg"}},
    }
    respx.get("https://graph.facebook.com/v20.0/11223344").mock(
        return_value=httpx.Response(200, json=mock_page_profile)
    )
    respx.get("https://graph.facebook.com/v20.0/11223344/insights").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    # Call callback endpoint
    resp = await client.post(
        "/api/v1/platforms/facebook/callback",
        json={"code": "mock_fb_code"},
        headers=headers,
    )
    assert resp.status_code == 201
    account_data = resp.json()
    assert account_data["platform"] == "facebook"
    assert account_data["platform_account_id"] == "11223344"
    assert account_data["account_name"] == "My Tech Brand"
    account_id = account_data["id"]

    # Verify listing accounts by platform
    list_res = await client.get("/api/v1/platforms?platform=facebook", headers=headers)
    assert list_res.status_code == 200
    accounts = list_res.json()
    assert len(accounts) == 1
    assert accounts[0]["id"] == account_id

    # Test sync
    respx.get("https://graph.facebook.com/v20.0/11223344/posts").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    sync_res = await client.post(f"/api/v1/platforms/{account_id}/sync", headers=headers)
    assert sync_res.status_code == 200
    sync_data = sync_res.json()
    assert sync_data["platform"] == "facebook"
    assert sync_data["channel_name"] == "My Tech Brand"


@pytest.mark.asyncio
@respx.mock
async def test_instagram_oauth_callback(client: AsyncClient, auth_headers):
    """Test Instagram OAuth callback discovering linked business account."""
    headers = await auth_headers(email="iguser@example.com")

    # Mock token exchange
    respx.get("https://graph.facebook.com/v20.0/oauth/access_token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "ig_user_token_short", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "ig_user_token_long", "expires_in": 5184000}),
        ]
    )

    # Mock /me/accounts returning page with linked IG
    mock_pages = {
        "data": [
            {
                "id": "page_999",
                "name": "Page 999",
                "access_token": "page_tok_999",
                "instagram_business_account": {
                    "id": "ig_biz_888",
                    "username": "ig_creator_888",
                    "name": "Creator 888",
                },
            }
        ]
    }
    respx.get("https://graph.facebook.com/v20.0/me/accounts").mock(
        return_value=httpx.Response(200, json=mock_pages)
    )

    # Mock IG profile
    mock_ig_profile = {
        "id": "ig_biz_888",
        "username": "ig_creator_888",
        "name": "Creator 888",
        "followers_count": 42000,
        "media_count": 88,
        "profile_picture_url": "https://example.com/ig.jpg",
    }
    respx.get("https://graph.facebook.com/v20.0/ig_biz_888").mock(
        return_value=httpx.Response(200, json=mock_ig_profile)
    )
    respx.get("https://graph.facebook.com/v20.0/ig_biz_888/insights").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    resp = await client.post(
        "/api/v1/platforms/instagram/callback",
        json={"code": "mock_ig_code"},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["platform"] == "instagram"
    assert data["platform_account_id"] == "ig_biz_888"
    assert data["account_handle"] == "@ig_creator_888"


@pytest.mark.asyncio
@respx.mock
async def test_threads_oauth_flow(client: AsyncClient, auth_headers):
    """Test Threads OAuth consent URL and callback linking account."""
    headers = await auth_headers(email="threadsuser@example.com")

    # 1. Authorize URL
    from app.api.v1.endpoints.platforms import threads_connector
    orig_app_id = threads_connector.app_id
    threads_connector.app_id = "threads-test-id"

    try:
        auth_res = await client.get("/api/v1/platforms/threads/authorize", headers=headers)
        assert auth_res.status_code == 200
        assert auth_res.json()["platform"] == "threads"
        assert "threads.net/oauth/authorize" in auth_res.json()["authorization_url"]

        # 2. Callback
        respx.post("https://graph.threads.net/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "th_short", "user_id": 556677})
        )
        respx.get("https://graph.threads.net/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "th_long", "expires_in": 5184000})
        )
        respx.get("https://graph.threads.net/v1.0/me").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "556677",
                    "username": "threads_guru",
                    "name": "Threads Guru",
                    "threads_profile_picture_url": "https://example.com/guru.jpg",
                },
            )
        )
        respx.get("https://graph.threads.net/v1.0/556677/threads_insights").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        cb_res = await client.post(
            "/api/v1/platforms/threads/callback",
            json={"code": "mock_threads_code"},
            headers=headers,
        )
        assert cb_res.status_code == 201
        th_data = cb_res.json()
        assert th_data["platform"] == "threads"
        assert th_data["platform_account_id"] == "556677"
        assert th_data["account_name"] == "Threads Guru"

    finally:
        threads_connector.app_id = orig_app_id
