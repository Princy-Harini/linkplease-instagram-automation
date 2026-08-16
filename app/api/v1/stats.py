from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.stats import StatsResponse
from app.services.stats_service import StatsService

router = APIRouter(tags=["Statistics"])

@router.get(
    "/stats",
    response_model=StatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get delivery and duplicate statistics",
    description="Returns live, concurrency-safe counts of sent, failed, queued, and blocked duplicate DMs."
)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    """
    Return delivery statistics computed directly from persisted database state.
    """
    return StatsService.get_stats(db)
