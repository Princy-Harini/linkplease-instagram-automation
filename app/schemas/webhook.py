from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class UserData(BaseModel):
    user_id: str
    username: Optional[str] = None

class CommentData(BaseModel):
    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None
    from_user: Optional[UserData] = Field(None, alias="from")

    class Config:
        populate_by_name = True

class WebhookPayload(BaseModel):
    event_id: str
    event_type: str
    sent_at: Optional[datetime] = None
    data: CommentData

    class Config:
        populate_by_name = True
