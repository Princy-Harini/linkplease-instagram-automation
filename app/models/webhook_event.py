from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON
from app.core.database import Base

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    event_id = Column(String(64), primary_key=True)
    event_type = Column(String(64), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), default="received", nullable=False)

    def __repr__(self) -> str:
        return f"<WebhookEvent event_id={self.event_id} status={self.status}>"
