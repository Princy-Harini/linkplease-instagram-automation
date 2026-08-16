from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class DMSendRequest(BaseModel):
    recipient_user_id: str
    message: str

class DMSendResponse(BaseModel):
    dm_id: str
    status: str

class DMStatusResponse(BaseModel):
    dm_id: str
    status: str
    recipient_user_id: Optional[str] = None
    updated_at: Optional[datetime] = None
