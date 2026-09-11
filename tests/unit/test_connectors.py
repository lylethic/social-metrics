"""Unit tests for BaseSocialConnector and YouTubeConnector."""

from datetime import datetime, timezone
import pytest
import respx
import httpx

from app.connectors.base import (
    BaseSocialConnector,
    ChannelProfile,
    ConnectorAuthError,
    ConnectorNotFoundError,
    ConnectorQuotaExceededError,
    ConnectorRateLimitError,
    PlatformPost,
    PostMetrics,
)
from app.connectors.youtube import YouTubeConnector


def test_base_connector_cannot_be_instantiated():
    """Verify that BaseSocialConnector is an abstract class."""
    with pytest.raises(TypeError):
        BaseSocialConnector()


def test_youtube_authorization_url():
    """Test generating YouTube OAuth2 consent URL."""
    connector = YouTubeConnector(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:5032/callback",
    )
    url = connector.get_authorization_url(state="test-state-123")
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=test-client-id" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A5032%2Fcallback" in url
    assert "state=test-state-123" in url
    assert "access_type=offline" in url


@pytest.mark.asyncio
async def test_youtube_authorization_url_missing_client_id():
    """Test error when YouTube client_id is missing."""
    connector = YouTubeConnector()
    connector.client_id = None
    with pytest.raises(ConnectorAuthError) as exc_info:
        connector.get_authorization_url(state="state")
    assert "client_id is not configured" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_authenticate_success():
    """Test exchanging auth code for tokens."""
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.mock_access_token",
                "refresh_token": "mock_refresh_token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/youtube.readonly",
            },
        )
    )

    connector = YouTubeConnector(client_id="id", client_secret="secret", redirect_uri="http://test")
    tokens = await connector.authenticate("mock_auth_code")

    assert tokens.access_token == "ya29.mock_access_token"
    assert tokens.refresh_token == "mock_refresh_token"
    assert tokens.expires_in == 3600


@pytest.mark.asyncio
@respx.mock
async def test_youtube_authenticate_failure():
    """Test handling OAuth exchange error."""
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "Code was expired"},
        )
    )

    connector = YouTubeConnector(client_id="id", client_secret="secret", redirect_uri="http://test")
    with pytest.raises(ConnectorAuthError) as exc_info:
        await connector.authenticate("expired_code")
    assert "Code was expired" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_refresh_token():
    """Test refreshing an access token."""
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.refreshed_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    connector = YouTubeConnector(client_id="id", client_secret="secret")
    tokens = await connector.refresh_token("existing_refresh_token")
    assert tokens.access_token == "ya29.refreshed_token"
    assert tokens.refresh_token == "existing_refresh_token"


@pytest.mark.asyncio
@respx.mock
async def test_get_channel_profile_success():
    """Test fetching channel profile by channel ID."""
    mock_channel_response = {
        "items": [
            {
                "id": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
                "snippet": {
                    "title": "Google Developers",
                    "customUrl": "@googledevelopers",
                    "thumbnails": {
                        "high": {"url": "https://example.com/avatar.jpg"}
                    },
                    "country": "US",
                },
                "statistics": {
                    "viewCount": "150000000",
                    "subscriberCount": "2300000",
                    "videoCount": "5400",
                    "hiddenSubscriberCount": False,
                },
                "contentDetails": {
                    "relatedPlaylists": {
                        "uploads": "UU_x5XG1OV2P6uZZ5FSM9Ttw"
                    }
                },
            }
        ]
    }

    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(200, json=mock_channel_response)
    )

    connector = YouTubeConnector(api_key="mock-api-key")
    profile = await connector.get_channel_profile("UC_x5XG1OV2P6uZZ5FSM9Ttw")

    assert profile.platform == "youtube"
    assert profile.platform_account_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert profile.account_name == "Google Developers"
    assert profile.account_handle == "@googledevelopers"
    assert profile.followers_count == 2300000
    assert profile.views_count == 150000000
    assert profile.total_videos_count == 5400
    assert profile.metadata_json["uploads_playlist_id"] == "UU_x5XG1OV2P6uZZ5FSM9Ttw"


@pytest.mark.asyncio
@respx.mock
async def test_get_channel_profile_not_found():
    """Test 404 when channel does not exist."""
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    connector = YouTubeConnector(api_key="mock-api-key")
    with pytest.raises(ConnectorNotFoundError):
        await connector.get_channel_profile("UC_nonexistent")


@pytest.mark.asyncio
@respx.mock
async def test_youtube_quota_exceeded():
    """Test handling YouTube quota exceeded error (HTTP 403 quotaExceeded)."""
    quota_error_body = {
        "error": {
            "code": 403,
            "message": "The request cannot be completed because you have exceeded your quota.",
            "errors": [
                {
                    "message": "The request cannot be completed because you have exceeded your quota.",
                    "domain": "youtube.quota",
                    "reason": "quotaExceeded",
                }
            ],
        }
    }

    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(403, json=quota_error_body)
    )

    connector = YouTubeConnector(api_key="mock-api-key")
    with pytest.raises(ConnectorQuotaExceededError) as exc_info:
        await connector.get_channel_profile("UC123")
    assert "10,000 units/day" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_rate_limit_and_backoff_recovery():
    """Test exponential backoff retries when encountering HTTP 429 and subsequent recovery."""
    channel_url = "https://www.googleapis.com/youtube/v3/channels"

    # First attempt returns 429, second attempt returns 200
    respx.get(channel_url).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "Rate limit"}}),
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC123",
                            "snippet": {"title": "Test Channel"},
                            "statistics": {"subscriberCount": "100", "viewCount": "1000", "videoCount": "5"},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
                        }
                    ]
                },
            ),
        ]
    )

    connector = YouTubeConnector(api_key="mock-api-key", max_retries=2, backoff_factor=0.01)
    profile = await connector.get_channel_profile("UC123")
    assert profile.account_name == "Test Channel"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_posts_success():
    """Test fetching channel videos through playlistItems and videos batch endpoint."""
    # 1. Mock get_channel_profile
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UC_channel_1",
                        "snippet": {"title": "Test Channel"},
                        "statistics": {"subscriberCount": "100", "viewCount": "1000", "videoCount": "2"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UU_channel_1"}},
                    }
                ]
            },
        )
    )

    # 2. Mock playlistItems
    respx.get("https://www.googleapis.com/youtube/v3/playlistItems").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "snippet": {
                            "publishedAt": "2026-09-01T12:00:00Z",
                            "resourceId": {"videoId": "vid_1"},
                        },
                        "contentDetails": {"videoId": "vid_1"},
                    },
                    {
                        "snippet": {
                            "publishedAt": "2026-09-02T12:00:00Z",
                            "resourceId": {"videoId": "vid_2"},
                        },
                        "contentDetails": {"videoId": "vid_2"},
                    },
                ]
            },
        )
    )

    # 3. Mock videos batch details
    respx.get("https://www.googleapis.com/youtube/v3/videos").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "vid_1",
                        "snippet": {
                            "title": "Long Video Tutorial",
                            "description": "Full tutorial on python",
                            "publishedAt": "2026-09-01T12:00:00Z",
                            "thumbnails": {"high": {"url": "https://example.com/vid1.jpg"}},
                        },
                        "statistics": {
                            "viewCount": "50000",
                            "likeCount": "2500",
                            "commentCount": "300",
                        },
                        "contentDetails": {"duration": "PT15M30S"},
                    },
                    {
                        "id": "vid_2",
                        "snippet": {
                            "title": "Short Tip #1",
                            "description": "Quick trick",
                            "publishedAt": "2026-09-02T12:00:00Z",
                            "thumbnails": {"high": {"url": "https://example.com/vid2.jpg"}},
                        },
                        "statistics": {
                            "viewCount": "100000",
                            "likeCount": "8000",
                            "commentCount": "500",
                        },
                        "contentDetails": {"duration": "PT45S"},
                    },
                ]
            },
        )
    )

    connector = YouTubeConnector(api_key="mock-key")
    posts = await connector.fetch_posts("UC_channel_1", limit=10)

    assert len(posts) == 2
    assert posts[0].platform_post_id == "vid_1"
    assert posts[0].post_type == "video"
    assert posts[0].title == "Long Video Tutorial"
    assert posts[0].metadata_json["views_count"] == 50000

    # Short detection
    assert posts[1].platform_post_id == "vid_2"
    assert posts[1].post_type == "short"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_post_metrics():
    """Test fetching video metrics and engagement rate calculation."""
    respx.get("https://www.googleapis.com/youtube/v3/videos").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "vid_test",
                        "statistics": {
                            "viewCount": "10000",
                            "likeCount": "400",
                            "commentCount": "100",
                        },
                    }
                ]
            },
        )
    )

    connector = YouTubeConnector(api_key="mock-key")
    metrics = await connector.fetch_post_metrics("vid_test")

    assert metrics.platform_post_id == "vid_test"
    assert metrics.views_count == 10000
    assert metrics.likes_count == 400
    assert metrics.comments_count == 100
    # ER = (400 + 100) / 10000 * 100 = 5.0%
    assert metrics.engagement_rate == 5.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_comments():
    """Test fetching comment threads for a video."""
    respx.get("https://www.googleapis.com/youtube/v3/commentThreads").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "comment_1",
                        "snippet": {
                            "totalReplyCount": 2,
                            "topLevelComment": {
                                "id": "comment_1",
                                "snippet": {
                                    "authorDisplayName": "Jane Doe",
                                    "authorProfileImageUrl": "https://example.com/jane.jpg",
                                    "textDisplay": "Awesome video!",
                                    "likeCount": 15,
                                    "publishedAt": "2026-09-03T10:00:00Z",
                                },
                            },
                        },
                    }
                ]
            },
        )
    )

    connector = YouTubeConnector(api_key="mock-key")
    comments = await connector.fetch_comments("vid_test", limit=5)

    assert len(comments) == 1
    assert comments[0].comment_id == "comment_1"
    assert comments[0].author_name == "Jane Doe"
    assert comments[0].content == "Awesome video!"
    assert comments[0].likes_count == 15
    assert comments[0].reply_count == 2
