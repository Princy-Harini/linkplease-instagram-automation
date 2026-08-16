import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import verify_webhook_signature
from app.core.logging import get_logger
from app.repositories.events_repo import EventsRepository
from app.schemas.webhook import WebhookPayload
from app.workers.tasks import process_webhook_event_task

logger = get_logger(__name__)
router = APIRouter(tags=["Webhook"])

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Ingest PseudoGram webhook events",
    description="Receives comment.created and comment.deleted events with signature verification and asynchronous queueing."
)
async def handle_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_pseudogram_signature: str = Header(None, alias="X-PseudoGram-Signature")
) -> dict:
    """
    Fast webhook ingestion endpoint (< 50ms response).
    Verifies signature, persists event for deduplication, and queues background processing.
    """
    raw_body = await request.body()

    # 1. Webhook Signature Verification (Part B Security)
    if not verify_webhook_signature(raw_body, x_pseudogram_signature):
        logger.warning("Rejected webhook request with invalid or missing signature.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature."
        )

    # 2. Parse payload
    try:
        data = json.loads(raw_body.decode("utf-8"))
        payload = WebhookPayload(**data)
    except Exception as exc:
        logger.warning(f"Malformed webhook JSON received: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON or schema validation failed."
        )

    # 3. Idempotent Event Persistence
    event, is_new = EventsRepository.insert_event_if_not_exists(
        db=db,
        event_id=payload.event_id,
        event_type=payload.event_type,
        sent_at=payload.sent_at,
        payload=data
    )

    if not is_new:
        logger.info(f"Duplicate event_id={payload.event_id} received. Skipping duplicate enqueue.")
        return {"status": "duplicate_ignored", "event_id": payload.event_id}

    # 4. Dispatch async processing to Celery background worker
    try:
        process_webhook_event_task.delay(payload.event_id)
    except Exception as exc:
        logger.error(f"Failed to enqueue Celery task for event {payload.event_id}: {exc}")
        # Note: Event is safely persisted in DB and can be recovered by reconciler/sweeper

    return {"status": "ok", "event_id": payload.event_id}
