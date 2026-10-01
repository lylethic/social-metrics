"""API Endpoints for Legal Documents (Terms of Service and Privacy Policy)."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.services.legal_service import legal_service

router = APIRouter(tags=["Legal"])


@router.get("/terms", response_class=HTMLResponse)
async def get_terms_of_service() -> HTMLResponse:
    """Terms of Service page for third-party platform API compliance."""
    return HTMLResponse(content=legal_service.get_terms_html(), status_code=200)


@router.get("/privacy", response_class=HTMLResponse)
async def get_privacy_policy() -> HTMLResponse:
    """Privacy Policy page for third-party platform API compliance."""
    return HTMLResponse(content=legal_service.get_privacy_html(), status_code=200)
