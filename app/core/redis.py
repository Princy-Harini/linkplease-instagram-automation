from typing import Optional
import redis
from app.core.config import get_settings

settings = get_settings()

_redis_client: Optional[redis.Redis] = None

def get_redis_client() -> redis.Redis:
    """Return a singleton Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5
        )
    return _redis_client
