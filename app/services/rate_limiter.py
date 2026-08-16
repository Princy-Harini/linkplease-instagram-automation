import time
import uuid
from typing import Tuple, Optional
import redis
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class RateLimiter:
    """
    Sliding window rate limiter backed by Redis.
    Guarantees that no more than `max_requests` (default: 10) are sent
    per `window_seconds` (default: 60s) across all workers.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        key_prefix: str = "ratelimit:pseudogram_dm",
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None
    ):
        self.redis = redis_client
        self.key = key_prefix
        self.lockout_key = f"{key_prefix}:lockout"
        settings = get_settings()
        self.max_requests = max_requests or settings.RATE_LIMIT_PER_MINUTE
        self.window_seconds = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS

    def acquire_slot(self) -> Tuple[bool, float]:
        """
        Attempt to acquire a rate limit slot for an outgoing DM request.
        
        Returns:
            Tuple[bool, float]:
            - (True, 0.0) if slot is acquired immediately.
            - (False, wait_seconds) if rate limit is exceeded or server is locked out (429).
        """
        now = time.time()

        try:
            # 1. Check if an explicit HTTP 429 lockout is in effect
            lockout_until = self.redis.get(self.lockout_key)
            if lockout_until:
                lockout_time = float(lockout_until)
                if lockout_time > now:
                    wait_seconds = lockout_time - now
                    logger.warning(
                        f"External rate limit active (429 lockout). Must wait {wait_seconds:.2f}s."
                    )
                    return False, max(wait_seconds, 1.0)
                else:
                    self.redis.delete(self.lockout_key)

            # 2. Redis pipeline for sliding window
            pipe = self.redis.pipeline()
            # Remove timestamps older than current window
            pipe.zremrangebyscore(self.key, "-inf", now - self.window_seconds)
            # Count items in the current rolling window
            pipe.zcard(self.key)
            # Fetch the oldest item in current window to calculate wait time if full
            pipe.zrange(self.key, 0, 0, withscores=True)
            _, count, oldest_items = pipe.execute()

            if count < self.max_requests:
                # Add new timestamp with unique member ID
                member_id = f"{now}:{uuid.uuid4().hex[:8]}"
                add_pipe = self.redis.pipeline()
                add_pipe.zadd(self.key, {member_id: now})
                add_pipe.expire(self.key, self.window_seconds + 10)
                add_pipe.execute()
                return True, 0.0
            else:
                # Window is saturated. Compute time until oldest request leaves window
                if oldest_items:
                    _, oldest_timestamp = oldest_items[0]
                    wait_seconds = (oldest_timestamp + self.window_seconds) - now
                    wait_seconds = max(0.5, wait_seconds)
                else:
                    wait_seconds = float(self.window_seconds)
                
                logger.info(
                    f"Rate limit reached ({count}/{self.max_requests} in {self.window_seconds}s). "
                    f"Required wait: {wait_seconds:.2f}s."
                )
                return False, wait_seconds

        except Exception as exc:
            logger.error(f"Redis rate limiter error: {exc}. Permitting request to proceed with caution.")
            return True, 0.0

    def set_lockout(self, retry_after_seconds: float) -> None:
        """Set an explicit cooldown period when receiving HTTP 429 Retry-After."""
        now = time.time()
        lockout_time = now + retry_after_seconds
        try:
            self.redis.set(self.lockout_key, str(lockout_time), ex=int(retry_after_seconds) + 5)
            logger.warning(f"Set 429 lockout for {retry_after_seconds}s until {lockout_time}")
        except Exception as exc:
            logger.error(f"Failed to set Redis lockout: {exc}")
