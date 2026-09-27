from fastapi import APIRouter
from app.api.v1.endpoints import auth, channels, insights, platforms, posts, ai, reports, webhooks

api_router = APIRouter()

# Include Auth Endpoints
api_router.include_router(auth.router)

# Include Platform Endpoints
api_router.include_router(platforms.router)

# Include Channels Endpoints
api_router.include_router(channels.router)

# Include Posts Endpoints
api_router.include_router(posts.router)

# Include Insights & Analytics Endpoints
api_router.include_router(insights.router)

# Include AI Insights & Sentiment Endpoints
api_router.include_router(ai.router)

# Include Reports & Export Endpoints
api_router.include_router(reports.router)

# Include Webhook Endpoints
api_router.include_router(webhooks.router)

