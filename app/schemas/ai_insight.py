"""Pydantic schemas for AI Sentiment Analysis, Topic Extraction, and Content Recommendations."""

import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class SentimentBreakdown(BaseModel):
    """Aggregated sentiment breakdown of audience comments."""
    positive: int = Field(0, description="Count of positive comments")
    positive_percentage: float = Field(0.0, description="Percentage of positive comments")
    neutral: int = Field(0, description="Count of neutral comments")
    neutral_percentage: float = Field(0.0, description="Percentage of neutral comments")
    negative: int = Field(0, description="Count of negative comments")
    negative_percentage: float = Field(0.0, description="Percentage of negative comments")
    toxic_or_spam: int = Field(0, description="Count of toxic, hate speech, or spam comments")
    toxic_or_spam_percentage: float = Field(0.0, description="Percentage of toxic or spam comments")
    overall_score: float = Field(0.0, description="Composite sentiment score from -1.0 (very negative) to +1.0 (very positive)")
    dominant_sentiment: str = Field("neutral", description="Dominant sentiment label: positive, neutral, negative, toxic")


class TopicSentimentItem(BaseModel):
    """Extracted topic/keyword with its associated sentiment."""
    topic: str = Field(..., description="Extracted topic or keyword phrase")
    mentions_count: int = Field(..., description="Number of times mentioned in analyzed comments")
    sentiment: str = Field("neutral", description="Associated sentiment: positive, neutral, negative")
    sample_quote: Optional[str] = Field(None, description="Representative comment excerpt")


class PostAIInsightResponse(BaseModel):
    """AI sentiment and topic analysis response for a specific post."""
    post_id: uuid.UUID
    platform: str
    platform_post_id: str
    post_title: Optional[str] = None
    total_comments_analyzed: int
    sentiment_breakdown: SentimentBreakdown
    top_topics: List[TopicSentimentItem] = Field(default_factory=list)
    audience_feedback_summary: str = Field(..., description="Natural language summary of audience feedback")
    actionable_takeaway: str = Field(..., description="Actionable recommendation for creator")
    analyzed_at: datetime


class BestPostingTime(BaseModel):
    """Optimal time window to publish content based on interaction patterns."""
    day_of_week: str = Field(..., description="Day of the week (e.g. Monday, Friday)")
    time_window: str = Field(..., description="Optimal hour window (e.g. 18:00 - 20:00 UTC)")
    reasoning: str = Field(..., description="Data-driven reason for this time slot")
    average_engagement_multiplier: float = Field(1.0, description="Historical engagement multiplier vs average")


class TrendingTopic(BaseModel):
    """Emerging or trending topic opportunity."""
    topic: str
    growth_trend: str = Field("increasing", description="increasing, stable, decreasing")
    engagement_potential: str = Field("high", description="high, medium, low")
    recommendation: str


class ContentRecommendationsResponse(BaseModel):
    """AI recommendations for publishing schedule, topics, and growth strategies."""
    user_id: uuid.UUID
    platform: Optional[str] = None
    best_times_to_post: List[BestPostingTime] = Field(default_factory=list)
    trending_topics: List[TrendingTopic] = Field(default_factory=list)
    actionable_recommendations: List[str] = Field(default_factory=list)
    generated_at: datetime


class ExecutiveSummaryResponse(BaseModel):
    """Executive level AI briefing summarizing performance across all connected channels."""
    user_id: uuid.UUID
    timeframe: str
    summary_headline: str
    summary_markdown: str
    top_highlights: List[str] = Field(default_factory=list)
    key_concerns_or_risks: List[str] = Field(default_factory=list)
    generated_at: datetime
