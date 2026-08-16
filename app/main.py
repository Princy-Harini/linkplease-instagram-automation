from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.core.database import Base, engine
from app.api.v1 import api_v1_router
# Ensure all models are imported so Base metadata knows about them
import app.models # noqa: F401

settings = get_settings()
setup_logging(settings.LOG_LEVEL)
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown."""
    logger.info("Initializing LinkPlease Instagram Automation Application...")
    try:
        # Create database tables if they do not exist
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully.")
    except Exception as exc:
        logger.error(f"Error during database initialization: {exc}")
    
    yield
    
    logger.info("Shutting down LinkPlease backend.")

def create_app() -> FastAPI:
    """FastAPI application factory."""
    application = FastAPI(
        title="LinkPlease Instagram Automation Backend",
        description="High-reliability backend service for Instagram keyword-triggered DM automation with rate limiting, retries, and duplicate prevention.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # CORS Middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    application.include_router(api_v1_router)

    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred."}
        )

    return application

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=(settings.ENVIRONMENT == "development")
    )
