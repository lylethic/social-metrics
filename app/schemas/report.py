"""Pydantic schemas for Report generation and exports."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ReportExportRequest(BaseModel):
    """Query parameters for exporting analytics reports."""
    format: str = Field("excel", description="Export format: excel or pdf")
    timeframe: str = Field("30d", description="Timeframe: 7d, 30d, 90d, or 365d")
    platform: Optional[str] = Field(None, description="Optional platform filter")
