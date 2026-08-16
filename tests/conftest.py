import os
import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import fakeredis

# Set test environment before imports
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["PSEUDOGRAM_BASE_URL"] = "https://pseudogram-api.onrender.com"
os.environ["PSEUDOGRAM_API_KEY"] = "test_api_key_12345"
os.environ["VERIFY_WEBHOOK_SIGNATURE"] = "false"

import app.core.database as db_module
from app.core.database import Base, get_db
from app.core.config import get_settings
from app.workers.celery_app import celery_app
from app.main import create_app
from app.services.rate_limiter import RateLimiter

# Configure Celery for isolated in-memory test execution
celery_app.conf.update(
    broker_url="memory://",
    result_backend="cache+memory://",
    task_always_eager=False,
)

# Create single in-memory SQLite engine with StaticPool
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Point app.core.database engine and SessionLocal to test_engine
db_module.engine = test_engine
db_module.SessionLocal = TestingSessionLocal

@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Provide a fresh isolated database for each test function."""
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)

@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden database dependency."""
    app = create_app()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture(scope="function")
def fake_redis() -> fakeredis.FakeRedis:
    """Provide an in-memory Redis instance with Lua support."""
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    client.flushall()
    return client

@pytest.fixture(scope="function")
def test_rate_limiter(fake_redis: fakeredis.FakeRedis) -> RateLimiter:
    """RateLimiter instance backed by fake_redis with 10 req/60s limits."""
    return RateLimiter(redis_client=fake_redis, max_requests=10, window_seconds=60)
