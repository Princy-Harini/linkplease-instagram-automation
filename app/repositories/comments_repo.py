from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.comment import Comment
from app.core.logging import get_logger

logger = get_logger(__name__)

class CommentsRepository:
    """Data access repository for tracking Instagram comments and their deletion state."""

    @staticmethod
    def upsert_comment_created(
        db: Session,
        comment_id: str,
        post_id: Optional[str] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        text: Optional[str] = None,
        comment_created_at: Optional[datetime] = None
    ) -> Comment:
        """
        Record a comment creation event.
        If a comment.deleted event already arrived out-of-order, preserve is_deleted=True.
        """
        comment = db.query(Comment).filter(Comment.comment_id == comment_id).first()
        now = datetime.now(timezone.utc)

        if not comment:
            comment = Comment(
                comment_id=comment_id,
                post_id=post_id,
                user_id=user_id,
                username=username,
                text=text,
                is_deleted=False,
                comment_created_at=comment_created_at,
                created_at=now,
                updated_at=now
            )
            db.add(comment)
        else:
            # Update fields if not already populated, but DO NOT overwrite is_deleted=True
            comment.post_id = post_id or comment.post_id
            comment.user_id = user_id or comment.user_id
            comment.username = username or comment.username
            comment.text = text or comment.text
            comment.comment_created_at = comment_created_at or comment.comment_created_at
            comment.updated_at = now

        db.commit()
        db.refresh(comment)
        return comment

    @staticmethod
    def mark_comment_deleted(db: Session, comment_id: str) -> Comment:
        """
        Mark a comment as deleted.
        Creates a placeholder record if comment.deleted arrives before comment.created.
        """
        comment = db.query(Comment).filter(Comment.comment_id == comment_id).first()
        now = datetime.now(timezone.utc)

        if not comment:
            comment = Comment(
                comment_id=comment_id,
                is_deleted=True,
                deleted_at=now,
                created_at=now,
                updated_at=now
            )
            db.add(comment)
        else:
            comment.is_deleted = True
            comment.deleted_at = now
            comment.updated_at = now

        db.commit()
        db.refresh(comment)
        return comment

    @staticmethod
    def get_comment(db: Session, comment_id: str) -> Optional[Comment]:
        return db.query(Comment).filter(Comment.comment_id == comment_id).first()
