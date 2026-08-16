import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
from app.core.database import Base

def generate_delivery_id() -> str:
    return f"deliv_{uuid.uuid4().hex[:14]}"

class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(String(36), primary_key=True, default=generate_delivery_id)
    user_id = Column(String(64), nullable=False, index=True)
    rule_id = Column(String(36), ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False, index=True)
    comment_id = Column(String(64), nullable=False)
    dm_id = Column(String(64), nullable=True, index=True)
    idempotency_key = Column(String(128), unique=True, nullable=False)
    status = Column(String(32), default="queued", nullable=False, index=True)  # queued, sending, sent, failed
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=5, nullable=False)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "rule_id", name="uq_deliveries_user_rule"),
    )

    def __repr__(self) -> str:
        return f"<Delivery id={self.id} user_id={self.user_id} rule_id={self.rule_id} status={self.status}>"
