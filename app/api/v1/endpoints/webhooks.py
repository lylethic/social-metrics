"""API Endpoints for Social Platform Webhooks."""

import hashlib
import hmac
import json
import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.platform_account import PlatformAccount
from app.workers.tasks_ingestion import async_sync_channel_metrics, async_sync_posts_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_tiktok_signature(
    raw_body: bytes,
    signature: Optional[str],
    secret: Optional[str],
    timestamp: Optional[str] = None,
) -> bool:
    """Verify HMAC-SHA256 signature from TikTok Webhook request."""
    if not secret:
        # If secret not set in environment, allow for testing/initial deployment
        logger.debug("[TikTok Webhook] Secret not configured, bypassing signature check.")
        return True

    if not signature:
        logger.warning("[TikTok Webhook] Missing signature header while secret is configured.")
        return False

    # TikTok computes HMAC SHA256 of raw body (or timestamp + raw body)
    computed_sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    if hmac.compare_digest(computed_sig, signature.strip()):
        return True

    # Check alternative: timestamp + body
    if timestamp:
        data_to_sign = timestamp.encode("utf-8") + raw_body
        alt_sig = hmac.new(secret.encode("utf-8"), data_to_sign, hashlib.sha256).hexdigest()
        if hmac.compare_digest(alt_sig, signature.strip()):
            return True

    logger.warning(f"[TikTok Webhook] Signature mismatch: computed={computed_sig} vs received={signature}")
    return False


@router.get("/tiktok", summary="TikTok Webhook Verification Handshake")
async def verify_tiktok_webhook(
    challenge: Optional[str] = Query(None, description="Challenge token sent by TikTok"),
):
    """Respond to TikTok Webhook URL verification challenge (GET)."""
    if challenge:
        logger.info(f"[TikTok Webhook] Received GET verification challenge: {challenge}")
        return PlainTextResponse(content=challenge, status_code=status.HTTP_200_OK)

    return {"status": "ok", "platform": "tiktok", "message": "TikTok webhook endpoint active"}


@router.post("/tiktok", summary="TikTok Webhook Event Receiver")
async def handle_tiktok_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    tiktok_signature: Optional[str] = Header(None, alias="tiktok-signature"),
    x_tiktok_signature: Optional[str] = Header(None, alias="x-tiktok-signature"),
    tiktok_timestamp: Optional[str] = Header(None, alias="tiktok-timestamp"),
    x_tiktok_timestamp: Optional[str] = Header(None, alias="x-tiktok-timestamp"),
):
    """Receive, verify, and process incoming webhook events from TikTok."""
    raw_body = await request.body()
    sig = tiktok_signature or x_tiktok_signature
    ts = tiktok_timestamp or x_tiktok_timestamp
    secret = settings.TIKTOK_WEBHOOK_SECRET or settings.TIKTOK_CLIENT_SECRET

    # Verify signature
    if not verify_tiktok_signature(raw_body=raw_body, signature=sig, secret=secret, timestamp=ts):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TikTok webhook signature",
        )

    # Parse payload
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as exc:
        logger.error(f"[TikTok Webhook] Failed to parse JSON body: {exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    # Handle POST challenge verification
    if "challenge" in payload:
        logger.info(f"[TikTok Webhook] Responding to POST challenge: {payload['challenge']}")
        return JSONResponse(
            content={"challenge": payload["challenge"]},
            status_code=status.HTTP_200_OK,
        )

    event_type = payload.get("event") or payload.get("event_type") or "unknown"
    logger.info(f"[TikTok Webhook] Received event: {event_type}")

    # Extract user open_id if available
    open_id = (
        payload.get("user_open_id")
        or payload.get("open_id")
        or payload.get("data", {}).get("user_open_id")
    )

    if not open_id and isinstance(payload.get("content"), dict):
        open_id = payload["content"].get("user_open_id") or payload["content"].get("open_id")

    account = None
    if open_id:
        q = select(PlatformAccount).where(
            PlatformAccount.platform == "tiktok",
            PlatformAccount.platform_account_id == str(open_id),
        )
        res = await db.execute(q)
        account = res.scalars().first()

    # Dispatch events
    if event_type in ("video.publish", "video.create", "video.update"):
        if account:
            logger.info(f"[TikTok Webhook] Enqueueing post metrics sync for TikTok account {account.id}")
            background_tasks.add_task(async_sync_posts_metrics, account_id=account.id, limit=20)
        else:
            logger.warning(f"[TikTok Webhook] No matching account found for open_id {open_id}")

    elif event_type in ("user.info.update", "user.update"):
        if account:
            logger.info(f"[TikTok Webhook] Enqueueing channel metrics sync for TikTok account {account.id}")
            background_tasks.add_task(async_sync_channel_metrics, account_id=account.id)

    elif event_type in ("authorization.cancel", "authorization.revoke"):
        if account:
            logger.info(f"[TikTok Webhook] Deactivating revoked TikTok account {account.id}")
            account.is_active = False
            await db.commit()

    elif event_type in ("echo", "ping", "verify"):
        return {"status": "ok", "message": "pong"}

    return {
        "status": "success",
        "platform": "tiktok",
        "event": event_type,
        "account_found": account is not None,
    }
