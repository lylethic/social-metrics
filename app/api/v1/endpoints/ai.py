"""API Endpoints for AI Insights, Comment Sentiment Analysis, and Content Recommendations."""

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.rate_limiter import rate_limiter
from app.models.user import User
from app.schemas.ai_insight import (
    ContentRecommendationsResponse,
    ExecutiveSummaryResponse,
    PostAIInsightResponse,
)
from app.services.ai_insight_service import ai_insight_service

router = APIRouter(prefix="/ai", tags=["AI Insights"])


@router.post(
    "/analyze-post/{post_id}",
    response_model=PostAIInsightResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter(times=20, seconds=60, scope="ai_analyze_post"))],
)
async def analyze_post_comments(
    post_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Analyze comment sentiment (positive, neutral, negative, toxic/spam),
    extract core topics, and generate audience feedback takeaways for a post.
    """
    try:
        return await ai_insight_service.analyze_post_insights(
            db=db,
            post_id=post_id,
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise NotFoundException(detail=str(exc))
    except Exception as exc:
        raise BadRequestException(detail=f"AI sentiment analysis error: {str(exc)}")


@router.get(
    "/recommendations",
    response_model=ContentRecommendationsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter(times=30, seconds=60, scope="ai_recommendations"))],
)
async def get_content_recommendations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Optional platform filter: youtube, facebook, instagram, threads"),
):
    """
    Get data-driven publishing recommendations: optimal posting time windows,
    high-retention trending topics, and growth strategies.
    """
    return await ai_insight_service.generate_recommendations(
        db=db,
        user_id=current_user.id,
        platform=platform,
    )


@router.get(
    "/executive-summary",
    response_model=ExecutiveSummaryResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter(times=30, seconds=60, scope="ai_executive_summary"))],
)
async def get_executive_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    timeframe: int = Query(30, ge=1, le=365, description="Number of days to summarize"),
):
    """
    Generate an executive-level performance briefing summarizing overall growth,
    highlights, and areas of concern across channels.
    """
    return await ai_insight_service.generate_executive_summary(
        db=db,
        user_id=current_user.id,
        timeframe_days=timeframe,
    )
