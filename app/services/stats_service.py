from sqlalchemy.orm import Session
from app.repositories.stats_repo import StatsRepository
from app.schemas.stats import StatsResponse

class StatsService:
    """Service for retrieving real-time delivery and duplicate statistics."""

    @staticmethod
    def get_stats(db: Session) -> StatsResponse:
        data = StatsRepository.get_stats(db)
        return StatsResponse(**data)
