from typing import Dict
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from app.models.delivery import Delivery
from app.models.blocked_duplicate import BlockedDuplicate
from app.core.logging import get_logger

logger = get_logger(__name__)

class StatsRepository:
    """Repository for aggregating persisted statistics and recording blocked duplicates."""

    @staticmethod
    def record_blocked_duplicate(
        db: Session,
        event_id: str,
        user_id: str,
        rule_id: str,
        comment_id: str
    ) -> bool:
        """
        Record a blocked duplicate DM attempt for the given rule.
        Uses unique constraint uq_blocked_dup_event_rule to prevent double-counting
        the same duplicate event.
        """
        blocked = BlockedDuplicate(
            event_id=event_id,
            user_id=user_id,
            rule_id=rule_id,
            comment_id=comment_id
        )
        try:
            db.add(blocked)
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False

    @staticmethod
    def get_stats(db: Session) -> Dict[str, int]:
        """
        Compute live, concurrency-safe delivery statistics directly from the database.
        """
        sent_count = (
            db.query(func.count(Delivery.id))
            .filter(Delivery.status == "sent")
            .scalar() or 0
        )

        failed_count = (
            db.query(func.count(Delivery.id))
            .filter(Delivery.status == "failed")
            .scalar() or 0
        )

        queued_count = (
            db.query(func.count(Delivery.id))
            .filter(Delivery.status.in_(["queued", "sending"]))
            .scalar() or 0
        )

        duplicates_blocked_count = (
            db.query(func.count(BlockedDuplicate.id))
            .scalar() or 0
        )

        return {
            "sent": int(sent_count),
            "failed": int(failed_count),
            "queued": int(queued_count),
            "duplicates_blocked": int(duplicates_blocked_count)
        }
