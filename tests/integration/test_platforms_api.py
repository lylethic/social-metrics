"""Integration tests for Platforms API endpoints."""

import pytest
import respx
import httpx
from httpx import AsyncClient

from app.core.config import settings


@pytest.fixture
def auth_headers(client: AsyncClient):
    """Fixture returning helper to register and log in a user."""
    async def _get_headers(email: str = "testuser@example.com", password: str = "password123"):
        # Register
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Test User"},
        )
        # Login
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        token = login_res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _get_headers


@pytest.mark.asyncio
async def test_get_youtube_authorize_url(client: AsyncClient, auth_headers):
    """Test getting YouTube OAuth consent URL."""
    headers = await auth_headers()
    # Temporarily ensure client_id is set
    original_client_id = settings.YOUTUBE_CLIENT_ID
    settings.YOUTUBE_CLIENT_ID = "mock-google-client-id"
    from app.api.v1.endpoints.platforms import youtube_connector
    youtube_connector.client_id = "mock-google-client-id"

    try:
        response = await client.get("/api/v1/platforms/youtube/authorize", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "youtube"
        assert "accounts.google.com" in data["authorization_url"]
        assert "client_id=mock-google-client-id" in data["authorization_url"]
        assert "state=" in data["authorization_url"]
    finally:
        settings.YOUTUBE_CLIENT_ID = original_client_id
        youtube_connector.client_id = original_client_id


@pytest.mark.asyncio
@respx.mock
async def test_connect_channel_by_id_and_crud(client: AsyncClient, auth_headers):
    """Test connecting a YouTube channel, listing, getting, syncing, and deleting it."""
    headers = await auth_headers()

    mock_channel_response = {
        "items": [
            {
                "id": "UC_test_chan_123",
                "snippet": {
                    "title": "Tech With Tim",
                    "customUrl": "@techwithtim",
                    "thumbnails": {"high": {"url": "https://example.com/avatar.jpg"}},
                },
                "statistics": {
                    "viewCount": "50000000",
                    "subscriberCount": "1200000",
                    "videoCount": "800",
                },
                "contentDetails": {
                    "relatedPlaylists": {"uploads": "UU_test_chan_123"}
                },
            }
        ]
    }

    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(200, json=mock_channel_response)
    )

    from app.api.v1.endpoints.platforms import youtube_connector
    from app.services.account_service import account_service
    youtube_connector.api_key = "test-key"
    account_service.youtube_connector.api_key = "test-key"


    # 1. Connect Channel
    connect_resp = await client.post(
        "/api/v1/platforms/youtube/connect-channel",
        json={"channel_id": "UC_test_chan_123"},
        headers=headers,
    )
    assert connect_resp.status_code == 201
    account_data = connect_resp.json()
    account_id = account_data["id"]
    assert account_data["platform"] == "youtube"
    assert account_data["platform_account_id"] == "UC_test_chan_123"
    assert account_data["account_name"] == "Tech With Tim"

    # 2. List accounts
    list_resp = await client.get("/api/v1/platforms", headers=headers)
    assert list_resp.status_code == 200
    accounts = list_resp.json()
    assert len(accounts) == 1
    assert accounts[0]["id"] == account_id

    # 3. Get single account
    get_resp = await client.get(f"/api/v1/platforms/{account_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == account_id

    # 4. Sync account (mock playlistItems & videos)
    respx.get("https://www.googleapis.com/youtube/v3/playlistItems").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "snippet": {
                            "publishedAt": "2026-09-01T12:00:00Z",
                            "resourceId": {"videoId": "vid_abc"},
                        },
                        "contentDetails": {"videoId": "vid_abc"},
                    }
                ]
            },
        )
    )
    respx.get("https://www.googleapis.com/youtube/v3/videos").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "vid_abc",
                        "snippet": {
                            "title": "FastAPI Masterclass",
                            "description": "Learn FastAPI",
                            "publishedAt": "2026-09-01T12:00:00Z",
                        },
                        "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "10"},
                        "contentDetails": {"duration": "PT10M"},
                    }
                ]
            },
        )
    )

    sync_resp = await client.post(f"/api/v1/platforms/{account_id}/sync", headers=headers)
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()
    assert sync_data["posts_synced_count"] == 1
    assert sync_data["channel_name"] == "Tech With Tim"

    # 5. Delete account
    del_resp = await client.delete(f"/api/v1/platforms/{account_id}", headers=headers)
    assert del_resp.status_code == 204

    # Verify deleted
    get_again = await client.get(f"/api/v1/platforms/{account_id}", headers=headers)
    assert get_again.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_connect_youtube_oauth_callback(client: AsyncClient, auth_headers):
    """Test full OAuth code exchange and channel connection via callback endpoint."""
    headers = await auth_headers(email="oauth_user@example.com")

    # Mock token exchange
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.oauth_token",
                "refresh_token": "mock_refresh_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    # Mock channels?mine=true
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UC_oauth_mine_channel",
                        "snippet": {
                            "title": "My Personal Channel",
                            "customUrl": "@mypersonalchannel",
                        },
                        "statistics": {
                            "viewCount": "20000",
                            "subscriberCount": "500",
                            "videoCount": "15",
                        },
                        "contentDetails": {"relatedPlaylists": {"uploads": "UU_oauth_mine_channel"}},
                    }
                ]
            },
        )
    )

    from app.api.v1.endpoints.platforms import youtube_connector
    youtube_connector.client_id = "test-client-id"
    youtube_connector.client_secret = "test-client-secret"

    callback_resp = await client.post(
        "/api/v1/platforms/youtube/callback",
        json={"code": "sample_oauth_code_123", "state": "sample_state"},
        headers=headers,
    )
    assert callback_resp.status_code == 201
    data = callback_resp.json()
    assert data["platform"] == "youtube"
    assert data["platform_account_id"] == "UC_oauth_mine_channel"
    assert data["account_name"] == "My Personal Channel"
    # Ensure sensitive tokens are NOT leaked in response
    assert "access_token" not in data
    assert "refresh_token" not in data
