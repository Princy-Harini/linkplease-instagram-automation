from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Boolean, DateTime
from app.core.database import Base

class Comment(Base):
    __tablename__ = "comments"

    comment_id = Column(String(64), primary_key=True)
    post_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=True, index=True)
    username = Column(String(255), nullable=True)
    text = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    comment_created_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self) -> str:
        return f"<Comment comment_id={self.comment_id} user_id={self.user_id} is_deleted={self.is_deleted}>"
