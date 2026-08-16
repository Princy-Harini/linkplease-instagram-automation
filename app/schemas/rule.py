from pydantic import BaseModel, Field, field_validator

class RuleCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=255, description="Trigger keyword for comment matching")
    dm_message: str = Field(..., min_length=1, max_length=2000, description="Direct message content to send")

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Keyword must not be empty or whitespace only.")
        return trimmed

    @field_validator("dm_message")
    @classmethod
    def validate_dm_message(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("DM message must not be empty or whitespace only.")
        return trimmed

class RuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str

    class Config:
        from_attributes = True
