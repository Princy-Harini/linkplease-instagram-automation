from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.delivery import Delivery, generate_delivery_id
from app.core.logging import get_logger

logger = get_logger(__name__)

class DeliveriesRepository:
    """Data access repository for direct message deliveries and lifecycle state transitions."""

    @staticmethod
    def create_delivery_if_not_exists(
        db: Session,
        user_id: str,
        rule_id: str,
        comment_id: str,
        idempotency_key: str,
        max_retries: int = 5
    ) -> Tuple[Optional[Delivery], bool]:
        """
        Atomically create a delivery record.
        Returns: (Delivery, is_new: bool)
        Guaranteed single insert per (user_id, rule_id) enforced by database unique constraint.
        """
        delivery = Delivery(
            id=generate_delivery_id(),
            user_id=user_id,
            rule_id=rule_id,
            comment_id=comment_id,
            idempotency_key=idempotency_key,
            status="queued",
            retry_count=0,
            max_retries=max_retries
        )
        try:
            db.add(delivery)
            db.commit()
            db.refresh(delivery)
            return delivery, True
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(Delivery)
                .filter(Delivery.user_id == user_id, Delivery.rule_id == rule_id)
                .first()
            )
            return existing, False

    @staticmethod
    def get_delivery_by_id(db: Session, delivery_id: str) -> Optional[Delivery]:
        return db.query(Delivery).filter(Delivery.id == delivery_id).first()

    @staticmethod
    def get_delivery_by_dm_id(db: Session, dm_id: str) -> Optional[Delivery]:
        return db.query(Delivery).filter(Delivery.dm_id == dm_id).first()

    @staticmethod
    def update_delivery_status(
        db: Session,
        delivery_id: str,
        status: str,
        dm_id: Optional[str] = None,
        last_error: Optional[str] = None,
        retry_count: Optional[int] = None,
        next_retry_at: Optional[datetime] = None,
        delivered_at: Optional[datetime] = None
    ) -> Optional[Delivery]:
        """Update delivery status and lifecycle metadata."""
        delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if not delivery:
            return None

        delivery.status = status
        if dm_id is not None:
            delivery.dm_id = dm_id
        if last_error is not None:
            delivery.last_error = last_error
        if retry_count is not None:
            delivery.retry_count = retry_count
        if next_retry_at is not None:
            delivery.next_retry_at = next_retry_at
        if delivered_at is not None:
            delivery.delivered_at = delivered_at

        delivery.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(delivery)
        return delivery
