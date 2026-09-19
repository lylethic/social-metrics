"""API Endpoints for Exporting Analytics Reports (Excel & PDF)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import BadRequestException
from app.core.rate_limiter import rate_limiter
from app.models.user import User
from app.services.report_service import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter(times=10, seconds=60, scope="reports_export"))],
)
async def export_report(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    format: str = Query("excel", description="Export format: 'excel' or 'pdf'"),
    timeframe: str = Query("30d", description="Timeframe: '7d', '30d', '90d', or '365d'"),
    platform: Optional[str] = Query(None, description="Optional platform filter: youtube, facebook, instagram, threads"),
):
    """
    Generate and download a comprehensive multi-channel analytics report in Excel (.xlsx) or PDF format.
    """
    # Parse days
    days_map = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = days_map.get(timeframe.lower(), 30)
    fmt = format.lower().strip()

    if fmt not in ["excel", "pdf"]:
        raise BadRequestException(detail="Unsupported export format. Choose 'excel' or 'pdf'.")

    if fmt == "excel":
        file_buffer = await report_service.generate_excel_report(
            db=db,
            user_id=current_user.id,
            timeframe_days=days,
            platform=platform,
        )
        filename = f"social_insight_report_{timeframe}.xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        file_buffer = await report_service.generate_pdf_report(
            db=db,
            user_id=current_user.id,
            timeframe_days=days,
            platform=platform,
        )
        filename = f"social_insight_report_{timeframe}.pdf"
        media_type = "application/pdf"

    return Response(
        content=file_buffer.getvalue(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
