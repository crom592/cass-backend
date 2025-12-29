import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1 import api_router
from app.middleware.audit import AuditLogMiddleware
from app.middleware.monitoring import (
    MonitoringMiddleware,
    configure_structured_logging,
    setup_db_event_listeners,
)
from app.jobs.report_batch import setup_report_scheduler
from app.jobs.sla_batch import start_sla_scheduler, stop_sla_scheduler, get_sla_scheduler
from app.core.sse import connection_manager

# Configure structured logging
if getattr(settings, "ENABLE_STRUCTURED_LOGGING", True):
    configure_structured_logging(
        log_level="DEBUG" if settings.DEBUG else "INFO",
        json_format=not settings.DEBUG  # Use JSON in production, plain text in debug
    )
else:
    logging.basicConfig(
        level=logging.INFO if not settings.DEBUG else logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events for the FastAPI application.
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Setup database query monitoring
    try:
        from app.core.database import engine
        setup_db_event_listeners(engine)
        logger.info("Database query monitoring initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize database monitoring: {e}")

    # Setup report batch scheduler
    try:
        scheduler = setup_report_scheduler(app)
        if scheduler:
            logger.info("Report batch scheduler initialized successfully")
        else:
            logger.warning("Report batch scheduler not initialized (APScheduler may not be installed)")
    except Exception as e:
        logger.error(f"Failed to initialize report scheduler: {e}")

    # Start SLA batch scheduler
    try:
        await start_sla_scheduler()
        logger.info("SLA batch scheduler started successfully")
    except Exception as e:
        logger.error(f"Failed to start SLA scheduler: {e}")

    yield

    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")

    # Stop SLA scheduler
    try:
        await stop_sla_scheduler()
        logger.info("SLA batch scheduler stopped successfully")
    except Exception as e:
        logger.error(f"Error stopping SLA scheduler: {e}")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Charger After-Service System API",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Performance monitoring middleware (outermost - runs first)
if getattr(settings, "ENABLE_PROMETHEUS_METRICS", True):
    app.add_middleware(MonitoringMiddleware)

# Audit log middleware
app.add_middleware(AuditLogMiddleware)

# Include API router
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns application health status including SLA scheduler status and SSE connections.
    """
    sla_scheduler = get_sla_scheduler()
    sla_status = sla_scheduler.get_status()
    sse_stats = connection_manager.get_stats()

    return {
        "status": "healthy",
        "schedulers": {
            "sla": {
                "running": sla_status["running"],
                "last_run": sla_status["last_run"],
                "run_count": sla_status["run_count"],
                "error_count": sla_status["error_count"]
            }
        },
        "sse": {
            "total_connections": sse_stats["total_connections"],
            "tenants": sse_stats["tenants"],
            "users": sse_stats["users"]
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
