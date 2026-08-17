from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""
    
    # Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/linkplease_db"

    # Redis Broker
    REDIS_URL: str = "redis://localhost:6379/0"

    # Mock PseudoGram API
    PSEUDOGRAM_BASE_URL: str = "https://pseudogram-api.onrender.com"
    PSEUDOGRAM_API_KEY: str = ""

    @field_validator("PSEUDOGRAM_API_KEY", "PSEUDOGRAM_BASE_URL", mode="before")
    @classmethod
    def clean_str_config(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().strip("'\"")
        return v

    # Webhook Security
    VERIFY_WEBHOOK_SIGNATURE: bool = False

    # Reliability & Rate Limiter Configuration
    MAX_RETRIES: int = 5
    RATE_LIMIT_PER_MINUTE: int = 10
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RECONCILIATION_INTERVAL_SECONDS: int = 3
    RECONCILIATION_MAX_ATTEMPTS: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
