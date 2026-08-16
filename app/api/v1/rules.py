from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.rule import RuleCreate, RuleResponse
from app.repositories.rules_repo import RulesRepository
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Rules"])

@router.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a comment keyword rule",
    description="Registers a keyword and direct message pair for automated response."
)
def create_rule(
    rule_in: RuleCreate,
    db: Session = Depends(get_db)
) -> RuleResponse:
    """
    Create and persist a new keyword rule.
    Returns HTTP 201 with rule_id, keyword, and dm_message.
    """
    try:
        rule = RulesRepository.create_rule(
            db=db,
            keyword=rule_in.keyword,
            dm_message=rule_in.dm_message
        )
        logger.info(f"Created rule: id={rule.id} keyword={rule.keyword!r}")
        return RuleResponse(
            rule_id=rule.id,
            keyword=rule.keyword,
            dm_message=rule.dm_message
        )
    except Exception as exc:
        logger.error(f"Failed to create rule: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist rule."
        )
