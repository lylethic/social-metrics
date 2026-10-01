"""Business logic services."""

from app.services.account_service import AccountService, account_service
from app.services.ai_insight_service import AIInsightService, ai_insight_service
from app.services.analytics_service import (
    AnalyticsService,
    analytics_service,
    calculate_engagement_rate,
    calculate_growth_rate,
)
from app.services.auth_service import AuthService, auth_service
from app.services.cache_service import CacheService, cache_service
from app.services.legal_service import LegalService, legal_service
from app.services.report_service import ReportService, report_service

__all__ = [
    "AuthService",
    "auth_service",
    "AccountService",
    "account_service",
    "AnalyticsService",
    "analytics_service",
    "calculate_engagement_rate",
    "calculate_growth_rate",
    "CacheService",
    "cache_service",
    "AIInsightService",
    "ai_insight_service",
    "ReportService",
    "report_service",
    "LegalService",
    "legal_service",
]
