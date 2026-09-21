"""Unit tests for Meta Ecosystem connectors (MetaBase, Facebook, Instagram, Threads)."""

import pytest
import respx
import httpx
from datetime import datetime, timezone

from app.connectors.base import (
    ChannelProfile,
    ConnectorAuthError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    OAuthTokenResponse,
    PlatformComment,
    PlatformPost,
    PostMetrics,
)
from app.connectors.facebook import FacebookConnector
from app.connectors.instagram import InstagramConnector
from app.connectors.meta_base import MetaBaseConnector
from app.connectors.threads import ThreadsConnector


# -------------------------------------------------------------
# MetaBaseConnector Tests
# -------------------------------------------------------------

def test_meta_base_get_authorization_url():
    """Test generating Meta OAuth authorization URL."""
    connector = MetaBaseConnector(app_id="test-app-id", redirect_uri="http://localhost:5032/callback")
    url = connector.get_authorization_url(state="test-state-123")
    assert "https://www.facebook.com/v20.0/dialog/oauth" in url
    assert "client_id=test-app-id" in url
    assert "state=test-state-123" in url
    assert "pages_show_list" in url


def test_meta_base_missing_app_id():
    """Test error when Meta app_id is missing."""
    connector = MetaBaseConnector(app_id=None)
    connector.app_id = None
    with pytest.raises(ConnectorAuthError) as exc_info:
        connector.get_authorization_url(state="state")
    assert "Meta app_id is not configured" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_meta_base_exchange_short_lived_token():
    """Test exchanging auth code for short-lived User Access Token."""
    respx.get("https://graph.facebook.com/v20.0/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "mock_short_lived_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    connector = MetaBaseConnector(app_id="id", app_secret="secret")
    tokens = await connector.exchange_code_for_short_lived_token(auth_code="mock_code")
    assert tokens.access_token == "mock_short_lived_token"
    assert tokens.expires_in == 3600


@pytest.mark.asyncio
@respx.mock
async def test_meta_base_exchange_long_lived_token():
    """Test upgrading short-lived token to 60-day long-lived User Token."""
    respx.get("https://graph.facebook.com/v20.0/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "mock_long_lived_token_60d",
                "token_type": "Bearer",
                "expires_in": 5184000,
            },
        )
    )

    connector = MetaBaseConnector(app_id="id", app_secret="secret")
    tokens = await connector.exchange_for_long_lived_token("mock_short_lived_token")
    assert tokens.access_token == "mock_long_lived_token_60d"
    assert tokens.expires_in == 5184000


@pytest.mark.asyncio
@respx.mock
async def test_meta_base_get_user_pages():
    """Test fetching managed Facebook Pages with linked Instagram accounts."""
    mock_pages_response = {
        "data": [
            {
                "id": "100200300",
                "name": "Social Insight Official",
                "category": "Software Company",
                "access_token": "page_access_token_123",
                "picture": {"data": {"url": "https://example.com/page.jpg"}},
                "instagram_business_account": {
                    "id": "17841400012345",
                    "username": "socialinsight_app",
                    "name": "Social Insight App",
                },
            }
        ]
    }

    respx.get("https://graph.facebook.com/v20.0/me/accounts").mock(
        return_value=httpx.Response(200, json=mock_pages_response)
    )

    connector = MetaBaseConnector(app_id="id", app_secret="secret")
    pages = await connector.get_user_pages("user_token")
    assert len(pages) == 1
    assert pages[0]["id"] == "100200300"
    assert pages[0]["instagram_business_account"]["username"] == "socialinsight_app"


@pytest.mark.asyncio
@respx.mock
async def test_meta_base_error_handling_token_expired():
    """Test error classification for expired Meta OAuth token (Code 190)."""
    respx.get("https://graph.facebook.com/v20.0/me/accounts").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "Error validating access token: Session has expired",
                    "type": "OAuthException",
                    "code": 190,
                    "error_subcode": 463,
                }
            },
        )
    )

    connector = MetaBaseConnector(app_id="id", app_secret="secret")
    with pytest.raises(ConnectorAuthError) as exc_info:
        await connector.get_user_pages("expired_token")
    assert "token invalid or expired" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_meta_base_error_handling_rate_limit():
    """Test error classification for Meta rate limit (Code 32 / 4)."""
    respx.get("https://graph.facebook.com/v20.0/100200300").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "(#32) Page request limit reached",
                    "type": "OAuthException",
                    "code": 32,
                }
            },
        )
    )

    connector = MetaBaseConnector(app_id="id", app_secret="secret")
    with pytest.raises(ConnectorRateLimitError) as exc_info:
        await connector.make_graph_request(endpoint="/100200300")
    assert "rate limit reached" in str(exc_info.value)


# -------------------------------------------------------------
# FacebookConnector Tests
# -------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_facebook_authenticate_success():
    """Test Facebook authentication flow (short to long lived token)."""
    # 1. Short lived exchange
    respx.get("https://graph.facebook.com/v20.0/oauth/access_token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "fb_short_token", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "fb_long_token", "expires_in": 5184000}),
        ]
    )

    connector = FacebookConnector(app_id="app123", app_secret="secret123")
    tokens = await connector.authenticate("auth_code")
    assert tokens.access_token == "fb_long_token"
    assert tokens.expires_in == 5184000


@pytest.mark.asyncio
@respx.mock
async def test_facebook_get_channel_profile():
    """Test retrieving Facebook Page profile and page insights."""
    mock_page = {
        "id": "100200300",
        "name": "AI Tech World",
        "username": "aitechworld",
        "about": "Exploring AI tools",
        "fan_count": 45000,
        "followers_count": 52000,
        "picture": {"data": {"url": "https://example.com/fb_avatar.jpg"}},
        "link": "https://facebook.com/aitechworld",
    }

    mock_insights = {
        "data": [
            {
                "name": "page_impressions",
                "period": "day",
                "values": [{"value": 15000}],
            },
            {
                "name": "page_views_total",
                "period": "day",
                "values": [{"value": 3500}],
            },
        ]
    }

    respx.get("https://graph.facebook.com/v20.0/100200300").mock(
        return_value=httpx.Response(200, json=mock_page)
    )
    respx.get("https://graph.facebook.com/v20.0/100200300/insights").mock(
        return_value=httpx.Response(200, json=mock_insights)
    )

    connector = FacebookConnector(app_id="id", app_secret="secret")
    profile = await connector.get_channel_profile(account_id="100200300", access_token="token")

    assert profile.platform == "facebook"
    assert profile.platform_account_id == "100200300"
    assert profile.account_name == "AI Tech World"
    assert profile.account_handle == "@aitechworld"
    assert profile.followers_count == 52000
    assert profile.views_count == 18500


@pytest.mark.asyncio
@respx.mock
async def test_facebook_fetch_posts():
    """Test fetching recent posts from a Facebook Page."""
    mock_posts = {
        "data": [
            {
                "id": "100200300_1001",
                "message": "Announcing our new feature release!\nCheck it out now.",
                "created_time": "2026-09-01T10:00:00+0000",
                "permalink_url": "https://facebook.com/posts/1001",
                "full_picture": "https://example.com/post_pic.jpg",
                "shares": {"count": 12},
                "reactions": {"summary": {"total_count": 140}},
                "comments": {"summary": {"total_count": 25}},
            }
        ]
    }

    respx.get("https://graph.facebook.com/v20.0/100200300/posts").mock(
        return_value=httpx.Response(200, json=mock_posts)
    )

    connector = FacebookConnector(app_id="id", app_secret="secret")
    posts = await connector.fetch_posts(account_id="100200300", limit=10, access_token="token")

    assert len(posts) == 1
    p = posts[0]
    assert p.platform == "facebook"
    assert p.platform_post_id == "100200300_1001"
    assert p.post_type == "photo"
    assert "Announcing our new feature release!" in p.title


@pytest.mark.asyncio
@respx.mock
async def test_facebook_fetch_post_metrics():
    """Test fetching reactions, comments, and engagement rate for Facebook post."""
    mock_post_detail = {
        "id": "100200300_1001",
        "shares": {"count": 15},
        "reactions": {"summary": {"total_count": 150}},
        "comments": {"summary": {"total_count": 35}},
    }
    mock_post_insights = {
        "data": [
            {
                "name": "post_impressions",
                "values": [{"value": 2000}],
            }
        ]
    }

    respx.get("https://graph.facebook.com/v20.0/100200300_1001").mock(
        return_value=httpx.Response(200, json=mock_post_detail)
    )
    respx.get("https://graph.facebook.com/v20.0/100200300_1001/insights").mock(
        return_value=httpx.Response(200, json=mock_post_insights)
    )

    connector = FacebookConnector(app_id="id", app_secret="secret")
    metrics = await connector.fetch_post_metrics(post_id="100200300_1001", access_token="token")

    assert metrics.platform_post_id == "100200300_1001"
    assert metrics.likes_count == 150
    assert metrics.comments_count == 35
    assert metrics.shares_count == 15
    assert metrics.views_count == 2000
    # ER = (150 + 35 + 15) / 2000 * 100% = 10.0%
    assert metrics.engagement_rate == 10.0


# -------------------------------------------------------------
# InstagramConnector Tests
# -------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_instagram_get_channel_profile():
    """Test fetching Instagram Professional profile and insights."""
    mock_profile = {
        "id": "17841400012345",
        "username": "super_creator",
        "name": "Super Creator",
        "biography": "Daily tech tutorials",
        "profile_picture_url": "https://example.com/ig.jpg",
        "followers_count": 85000,
        "follows_count": 250,
        "media_count": 120,
        "website": "https://creator.com",
    }

    mock_insights = {
        "data": [
            {
                "name": "impressions",
                "values": [{"value": 45000}],
            },
            {
                "name": "reach",
                "values": [{"value": 30000}],
            },
        ]
    }

    respx.get("https://graph.facebook.com/v20.0/17841400012345").mock(
        return_value=httpx.Response(200, json=mock_profile)
    )
    respx.get("https://graph.facebook.com/v20.0/17841400012345/insights").mock(
        return_value=httpx.Response(200, json=mock_insights)
    )

    connector = InstagramConnector(app_id="id", app_secret="secret")
    profile = await connector.get_channel_profile(account_id="17841400012345", access_token="token")

    assert profile.platform == "instagram"
    assert profile.platform_account_id == "17841400012345"
    assert profile.account_name == "Super Creator"
    assert profile.account_handle == "@super_creator"
    assert profile.followers_count == 85000
    assert profile.total_videos_count == 120
    assert profile.views_count == 75000


@pytest.mark.asyncio
@respx.mock
async def test_instagram_fetch_posts():
    """Test fetching media items (reels, photos) from Instagram."""
    mock_media = {
        "data": [
            {
                "id": "1790011223344",
                "caption": "Check out this 60-second AI tutorial! #ai #tech",
                "media_type": "VIDEO",
                "media_product_type": "REELS",
                "media_url": "https://example.com/reel.mp4",
                "thumbnail_url": "https://example.com/reel_thumb.jpg",
                "permalink": "https://instagram.com/reel/123",
                "timestamp": "2026-09-02T14:30:00+0000",
                "like_count": 850,
                "comments_count": 45,
            }
        ]
    }

    respx.get("https://graph.facebook.com/v20.0/17841400012345/media").mock(
        return_value=httpx.Response(200, json=mock_media)
    )

    connector = InstagramConnector(app_id="id", app_secret="secret")
    posts = await connector.fetch_posts(account_id="17841400012345", access_token="token")

    assert len(posts) == 1
    p = posts[0]
    assert p.platform == "instagram"
    assert p.platform_post_id == "1790011223344"
    assert p.post_type == "reel"


@pytest.mark.asyncio
@respx.mock
async def test_instagram_fetch_post_metrics():
    """Test fetching metrics (plays, saves, likes) for Instagram Reel."""
    mock_media_info = {
        "id": "1790011223344",
        "like_count": 850,
        "comments_count": 45,
        "media_type": "VIDEO",
        "media_product_type": "REELS",
    }
    mock_media_insights = {
        "data": [
            {"name": "reach", "values": [{"value": 12000}]},
            {"name": "plays", "values": [{"value": 15000}]},
            {"name": "saved", "values": [{"value": 320}]},
            {"name": "shares", "values": [{"value": 85}]},
        ]
    }

    respx.get("https://graph.facebook.com/v20.0/1790011223344").mock(
        return_value=httpx.Response(200, json=mock_media_info)
    )
    respx.get("https://graph.facebook.com/v20.0/1790011223344/insights").mock(
        return_value=httpx.Response(200, json=mock_media_insights)
    )

    connector = InstagramConnector(app_id="id", app_secret="secret")
    metrics = await connector.fetch_post_metrics(post_id="1790011223344", access_token="token")

    assert metrics.views_count == 15000
    assert metrics.likes_count == 850
    assert metrics.comments_count == 45
    assert metrics.saves_count == 320
    assert metrics.shares_count == 85
    assert metrics.engagement_rate > 0.0


# -------------------------------------------------------------
# ThreadsConnector Tests
# -------------------------------------------------------------

def test_threads_authorization_url():
    """Test generating Official Threads OAuth2 consent URL."""
    connector = ThreadsConnector(
        app_id="threads-app-id",
        app_secret="threads-secret",
        redirect_uri="http://localhost:5032/threads/callback",
    )
    url = connector.get_authorization_url(state="state_threads_123")
    assert "https://threads.net/oauth/authorize" in url
    assert "client_id=threads-app-id" in url
    assert "threads_basic" in url
    assert "state=state_threads_123" in url


@pytest.mark.asyncio
@respx.mock
async def test_threads_authenticate_success():
    """Test Threads token exchange (short-lived then long-lived)."""
    # 1. Short-lived token
    respx.post("https://graph.threads.net/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "th_short_token", "user_id": 99887766},
        )
    )
    # 2. Long-lived token
    respx.get("https://graph.threads.net/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "th_long_token", "expires_in": 5184000, "token_type": "Bearer"},
        )
    )

    connector = ThreadsConnector(app_id="id", app_secret="secret")
    tokens = await connector.authenticate("mock_auth_code")

    assert tokens.access_token == "th_long_token"
    assert tokens.expires_in == 5184000


@pytest.mark.asyncio
@respx.mock
async def test_threads_refresh_token():
    """Test refreshing a long-lived Threads token."""
    respx.get("https://graph.threads.net/refresh_access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "th_refreshed_token", "expires_in": 5184000, "token_type": "Bearer"},
        )
    )

    connector = ThreadsConnector(app_id="id", app_secret="secret")
    tokens = await connector.refresh_token("existing_token")
    assert tokens.access_token == "th_refreshed_token"
    assert tokens.expires_in == 5184000


@pytest.mark.asyncio
@respx.mock
async def test_threads_get_channel_profile():
    """Test fetching Threads user profile and insights."""
    mock_me = {
        "id": "99887766",
        "username": "threads_dev",
        "name": "Threads Developer",
        "threads_profile_picture_url": "https://example.com/threads.jpg",
        "threads_biography": "Coding with Python & FastAPI",
    }
    mock_insights = {
        "data": [
            {"name": "views", "total_value": {"value": 85000}},
            {"name": "followers_count", "total_value": {"value": 14200}},
            {"name": "likes", "total_value": {"value": 6200}},
            {"name": "replies", "total_value": {"value": 450}},
        ]
    }

    respx.get("https://graph.threads.net/v1.0/me").mock(
        return_value=httpx.Response(200, json=mock_me)
    )
    respx.get("https://graph.threads.net/v1.0/99887766/threads_insights").mock(
        return_value=httpx.Response(200, json=mock_insights)
    )

    connector = ThreadsConnector(app_id="id", app_secret="secret")
    profile = await connector.get_channel_profile(account_id="me", access_token="token")

    assert profile.platform == "threads"
    assert profile.platform_account_id == "99887766"
    assert profile.account_name == "Threads Developer"
    assert profile.account_handle == "@threads_dev"
    assert profile.followers_count == 14200
    assert profile.views_count == 85000


@pytest.mark.asyncio
@respx.mock
async def test_threads_fetch_posts():
    """Test fetching threads posts."""
    mock_threads = {
        "data": [
            {
                "id": "thread_post_1",
                "text": "Excited to launch our Meta connectors today!\nWhat platforms do you use?",
                "media_type": "TEXT_POST",
                "media_product_type": "THREADS",
                "permalink": "https://threads.net/@dev/post/1",
                "timestamp": "2026-09-03T11:00:00+0000",
            }
        ]
    }

    respx.get("https://graph.threads.net/v1.0/me/threads").mock(
        return_value=httpx.Response(200, json=mock_threads)
    )

    connector = ThreadsConnector(app_id="id", app_secret="secret")
    posts = await connector.fetch_posts(account_id="me", access_token="token")

    assert len(posts) == 1
    p = posts[0]
    assert p.platform == "threads"
    assert p.platform_post_id == "thread_post_1"
    assert p.post_type == "thread"
    assert "Excited to launch" in p.title


@pytest.mark.asyncio
@respx.mock
async def test_threads_fetch_post_metrics():
    """Test fetching metrics (views, likes, replies, reposts) for a thread."""
    mock_insights = {
        "data": [
            {"name": "views", "values": [{"value": 1500}]},
            {"name": "likes", "values": [{"value": 120}]},
            {"name": "replies", "values": [{"value": 30}]},
            {"name": "reposts", "values": [{"value": 15}]},
        ]
    }

    respx.get("https://graph.threads.net/v1.0/thread_post_1/insights").mock(
        return_value=httpx.Response(200, json=mock_insights)
    )

    connector = ThreadsConnector(app_id="id", app_secret="secret")
    metrics = await connector.fetch_post_metrics(post_id="thread_post_1", access_token="token")

    assert metrics.views_count == 1500
    assert metrics.likes_count == 120
    assert metrics.comments_count == 30
    assert metrics.shares_count == 15
    # ER = (120 + 30 + 15) / 1500 * 100% = 11.0%
    assert metrics.engagement_rate == 11.0
