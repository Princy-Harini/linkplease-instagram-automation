import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from app.core.database import Base

def generate_rule_id() -> str:
    return f"rule_{uuid.uuid4().hex[:14]}"

class Rule(Base):
    __tablename__ = "rules"

    id = Column(String(36), primary_key=True, default=generate_rule_id)
    keyword = Column(String(255), nullable=False, index=True)
    dm_message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self) -> str:
        return f"<Rule id={self.id} keyword={self.keyword!r}>"
