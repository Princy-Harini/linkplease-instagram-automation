import time
import pytest
from app.services.rate_limiter import RateLimiter

def test_rate_limiter_allows_under_limit(test_rate_limiter: RateLimiter):
    # Allow 10 requests immediately
    for i in range(10):
        allowed, wait = test_rate_limiter.acquire_slot()
        assert allowed is True
        assert wait == 0.0

def test_rate_limiter_blocks_11th_request(test_rate_limiter: RateLimiter):
    # Fill 10 slots
    for i in range(10):
        allowed, _ = test_rate_limiter.acquire_slot()
        assert allowed is True

    # 11th request must be rejected with positive wait time
    allowed, wait_seconds = test_rate_limiter.acquire_slot()
    assert allowed is False
    assert wait_seconds > 0.0
    assert wait_seconds <= 60.0

def test_rate_limiter_429_lockout(test_rate_limiter: RateLimiter):
    # Set explicit 15 second lockout
    test_rate_limiter.set_lockout(15.0)

    allowed, wait_seconds = test_rate_limiter.acquire_slot()
    assert allowed is False
    assert wait_seconds > 10.0
