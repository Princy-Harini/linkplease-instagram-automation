from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import get_db
from app.core.redis import get_redis_client

router = APIRouter(tags=["Health"])

@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Service Health Check"
)
def health_check(db: Session = Depends(get_db)) -> dict:
    """Check database and redis connectivity."""
    db_ok = False
    redis_ok = False

    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    try:
        r = get_redis_client()
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    overall = "healthy" if db_ok else "degraded"
    return {
        "status": overall,
        "database": "connected" if db_ok else "disconnected",
        "redis": "connected" if redis_ok else "disconnected"
    }
