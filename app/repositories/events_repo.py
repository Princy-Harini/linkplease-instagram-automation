from datetime import datetime
from typing import Optional, Tuple, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.webhook_event import WebhookEvent
from app.core.logging import get_logger

logger = get_logger(__name__)

class EventsRepository:
    """Data access repository for webhook events (idempotency layer)."""

    @staticmethod
    def insert_event_if_not_exists(
        db: Session,
        event_id: str,
        event_type: str,
        sent_at: Optional[datetime],
        payload: Dict[str, Any]
    ) -> Tuple[Optional[WebhookEvent], bool]:
        """
        Atomically insert a webhook event.
        Returns: (WebhookEvent, is_new: bool)
        If event_id already exists, is_new is False.
        """
        # Fast query check
        existing = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
        if existing:
            return existing, False

        event = WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            sent_at=sent_at,
            payload=payload,
            status="received"
        )
        try:
            db.add(event)
            db.commit()
            db.refresh(event)
            return event, True
        except IntegrityError:
            db.rollback()
            existing = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
            return existing, False

    @staticmethod
    def get_event_by_id(db: Session, event_id: str) -> Optional[WebhookEvent]:
        return db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()

    @staticmethod
    def update_event_status(db: Session, event_id: str, status: str) -> None:
        event = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
        if event:
            event.status = status
            db.commit()
