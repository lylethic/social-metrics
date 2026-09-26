from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.redis import close_redis_pool, init_redis_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown events."""
    # Startup
    try:
        await init_redis_pool()
        print("[Startup] Redis connection pool initialized.")
    except Exception as e:
        print(f"[Startup Warning] Could not connect to Redis: {e}")

    yield

    # Shutdown
    await close_redis_pool()
    print("[Shutdown] Redis connection pool closed.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Microservice API for Social Media Insights Aggregation & AI Sentiment Analysis",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Set CORS middleware
if settings.BACKEND_CORS_ORIGINS:
    origins = [str(o).rstrip("/") for o in settings.BACKEND_CORS_ORIGINS]
    if settings.FRONTEND_URL and settings.FRONTEND_URL.rstrip("/") not in origins:
        origins.append(settings.FRONTEND_URL.rstrip("/"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if "*" not in origins else [],
        allow_origin_regex=r"^https?://.*" if "*" in origins else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health", tags=["Healthcheck"], status_code=status.HTTP_200_OK)
@app.get(f"{settings.API_V1_STR}/health", tags=["Healthcheck"], status_code=status.HTTP_200_OK)
async def health_check():
    """Service healthcheck endpoint."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "ai_provider": settings.AI_PROVIDER,
        "groq_model": settings.GROQ_MODEL,
    }


_LEGAL_CSS = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1f2937; max-width: 860px; margin: 0 auto; padding: 40px 20px; background-color: #f9fafb; }
    .card { background: #ffffff; border-radius: 12px; padding: 36px 40px; box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06); }
    h1 { color: #111827; font-size: 28px; margin-bottom: 8px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; }
    h2 { color: #374151; font-size: 20px; margin-top: 28px; margin-bottom: 12px; }
    p, li { color: #4b5563; font-size: 15px; }
    ul { padding-left: 24px; margin-bottom: 16px; }
    li { margin-bottom: 8px; }
    .badge { display: inline-block; background: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 9999px; font-size: 13px; font-weight: 600; margin-bottom: 16px; }
    .footer { margin-top: 36px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 13px; color: #9ca3af; text-align: center; }
"""


@app.get("/terms", tags=["Legal"])
@app.get(f"{settings.API_V1_STR}/terms", tags=["Legal"])
async def terms_of_service():
    """Terms of Service page for third-party platform API compliance."""
    from fastapi.responses import HTMLResponse
    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Terms of Service - {settings.PROJECT_NAME}</title>
    <style>{_LEGAL_CSS}</style>
</head>
<body>
    <div class="card">
        <span class="badge">Legal Document</span>
        <h1>Terms of Service</h1>
        <p><em>Last updated: September 2026</em></p>
        
        <p>Welcome to <strong>{settings.PROJECT_NAME}</strong>. By accessing or using our application, you agree to be bound by these Terms of Service.</p>
        
        <h2>1. Description of Service</h2>
        <p>{settings.PROJECT_NAME} provides cross-platform social media analytics, performance metrics aggregation, and AI-driven content insights for creators and businesses across supported platforms (YouTube, Meta Facebook/Instagram, TikTok, and Threads).</p>
        
        <h2>2. Third-Party Platform Policies</h2>
        <p>Our service integrates with official third-party APIs. By using our service with your social accounts, you also agree to comply with:</p>
        <ul>
            <li><strong>YouTube:</strong> YouTube Terms of Service (<a href="https://www.youtube.com/t/terms" target="_blank">https://www.youtube.com/t/terms</a>) and Google Privacy Policy.</li>
            <li><strong>Meta:</strong> Meta Platform Terms and Developer Policies.</li>
            <li><strong>TikTok:</strong> TikTok Developer Terms of Service and API Terms of Service.</li>
        </ul>
        
        <h2>3. User Account and Data Access</h2>
        <p>To use analytics features, you may authenticate your social media accounts via OAuth 2.0. We request only the minimal permissions necessary (such as read-only access to channel statistics, posts, and metrics). We will never post, comment, or make unauthorized modifications to your accounts.</p>
        
        <h2>4. Data Ownership & Revocation</h2>
        <p>You retain full ownership of all your content and platform data. You can disconnect your accounts or revoke API access at any time through our dashboard or directly in your Google, Meta, or TikTok account security settings.</p>
        
        <h2>5. Limitation of Liability</h2>
        <p>The service is provided on an "as is" and "as available" basis without warranties of any kind. We are not liable for any downtime, API modifications, or data limitations imposed by third-party platform providers.</p>
        
        <h2>6. Contact Us</h2>
        <p>If you have any questions regarding these Terms of Service, please contact us at: <code>support@socialinsight.dev</code>.</p>
        
        <div class="footer">
            &copy; 2026 {settings.PROJECT_NAME}. All rights reserved.
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=content, status_code=200)


@app.get("/privacy", tags=["Legal"])
@app.get(f"{settings.API_V1_STR}/privacy", tags=["Legal"])
async def privacy_policy():
    """Privacy Policy page for third-party platform API compliance."""
    from fastapi.responses import HTMLResponse
    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy - {settings.PROJECT_NAME}</title>
    <style>{_LEGAL_CSS}</style>
</head>
<body>
    <div class="card">
        <span class="badge">Privacy Notice</span>
        <h1>Privacy Policy</h1>
        <p><em>Last updated: September 2026</em></p>
        
        <p>This Privacy Policy explains how <strong>{settings.PROJECT_NAME}</strong> collects, uses, and protects your information when you use our social media analytics platform.</p>
        
        <h2>1. Information We Collect</h2>
        <ul>
            <li><strong>Account Information:</strong> Your user profile details (such as email, name, and registered identifiers).</li>
            <li><strong>Platform Data:</strong> When you connect a social platform (YouTube, Meta, TikTok), we collect public metadata including channel name, subscriber/follower counts, video/post performance statistics (views, likes, shares, comments), and published media timestamps.</li>
            <li><strong>Authentication Tokens:</strong> OAuth 2.0 access and refresh tokens used to retrieve your statistics securely on your behalf. All sensitive tokens are encrypted using AES/Fernet encryption at rest.</li>
        </ul>
        
        <h2>2. How We Use Your Information</h2>
        <ul>
            <li>To display consolidated analytics dashboards and performance trends.</li>
            <li>To calculate engagement metrics, growth benchmarks, and generate AI-powered optimization insights.</li>
            <li>We <strong>DO NOT</strong> sell, rent, or trade your personal or platform data to any third parties or advertisers.</li>
        </ul>
        
        <h2>3. Third-Party API Services & Compliance</h2>
        <p>Our application uses official API services:</p>
        <ul>
            <li><strong>Google / YouTube API Services:</strong> We adhere to the <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank">Google API Services User Data Policy</a>, including the Limited Use requirements.</li>
            <li><strong>Meta Graph API:</strong> We adhere to the Meta Data Policy and Developer Terms.</li>
            <li><strong>TikTok API:</strong> We strictly adhere to TikTok's Partner & Developer Data Guidelines.</li>
        </ul>
        
        <h2>4. Data Storage and Security</h2>
        <p>We implement industry-standard security safeguards. OAuth tokens are encrypted at rest with cryptographic ciphers, and all network communications are transmitted exclusively over secure HTTPS/TLS encryption.</p>
        
        <h2>5. Data Retention & Deletion Instructions</h2>
        <p>You have full control over your data:</p>
        <ul>
            <li><strong>Disconnecting Accounts:</strong> You can disconnect any platform account at any time in the Platforms Dashboard. Disconnecting immediately removes associated access tokens from our system.</li>
            <li><strong>Revoking Access:</strong> You can revoke permissions directly via <a href="https://myaccount.google.com/permissions" target="_blank">Google Security Settings</a>, Meta Business Integrations, or TikTok Authorized Apps.</li>
            <li><strong>Complete Data Deletion:</strong> To request complete deletion of your account and historical metrics data, please email <code>support@socialinsight.dev</code> with the subject "Data Deletion Request". We process all deletion requests within 48 hours.</li>
        </ul>
        
        <h2>6. Contact Us</h2>
        <p>For inquiries or concerns about our privacy practices, please contact our data protection team at: <code>support@socialinsight.dev</code>.</p>
        
        <div class="footer">
            &copy; 2026 {settings.PROJECT_NAME}. All rights reserved.
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=content, status_code=200)


# Include API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)
