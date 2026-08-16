from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from app.core.database import Base

class BlockedDuplicate(Base):
    __tablename__ = "blocked_duplicates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), nullable=False)
    user_id = Column(String(64), nullable=False, index=True)
    rule_id = Column(String(36), nullable=False, index=True)
    comment_id = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", "rule_id", name="uq_blocked_dup_event_rule"),
    )

    def __repr__(self) -> str:
        return f"<BlockedDuplicate user_id={self.user_id} rule_id={self.rule_id} event_id={self.event_id}>"
