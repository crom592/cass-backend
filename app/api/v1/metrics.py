"""
Metrics API endpoints for CASS backend.

Provides Prometheus-format metrics export, health checks,
and JSON statistics summary.
"""

from fastapi import APIRouter, Response, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
import logging

from app.core.database import get_db
from app.services.metrics_service import metrics_collector, PROMETHEUS_AVAILABLE
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/metrics",
    summary="Prometheus Metrics",
    description="Export metrics in Prometheus text format for scraping",
    response_class=PlainTextResponse,
    tags=["monitoring"]
)
async def get_prometheus_metrics():
    """
    Export metrics in Prometheus format.

    This endpoint is designed to be scraped by Prometheus or compatible
    monitoring systems. Returns metrics including:

    - HTTP request counts by method, endpoint, and status code
    - Request duration histograms
    - Error counts
    - Database query statistics
    - Active connections
    - Memory usage
    - Application uptime

    Returns:
        Prometheus text format metrics
    """
    try:
        metrics_data = metrics_collector.get_prometheus_metrics()
        content_type = metrics_collector.get_prometheus_content_type()

        return Response(
            content=metrics_data,
            media_type=content_type,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    except Exception as e:
        logger.error(f"Failed to generate Prometheus metrics: {e}")
        return PlainTextResponse(
            content=f"# Error generating metrics: {str(e)}\n",
            status_code=500
        )


@router.get(
    "/metrics/health",
    summary="Detailed Health Check",
    description="Get detailed health status including system resources and component status",
    response_class=JSONResponse,
    tags=["monitoring"]
)
async def get_health_details(
    db: AsyncSession = Depends(get_db),
    include_db_check: bool = True
):
    """
    Get detailed health check information.

    Provides comprehensive health status including:
    - Application uptime
    - Memory and CPU usage
    - Database connectivity
    - Request statistics and error rates
    - Active connections
    - Any identified health issues

    Query Parameters:
        include_db_check: Whether to perform a database connectivity check (default: true)

    Returns:
        JSON object with detailed health information
    """
    try:
        health_data = metrics_collector.get_health_details()

        # Perform database health check if requested
        if include_db_check:
            try:
                # Execute a simple query to verify database connectivity
                result = await db.execute(text("SELECT 1"))
                result.scalar()
                health_data["database"]["healthy"] = True
                health_data["database"]["connection"] = "ok"
            except Exception as db_error:
                health_data["database"]["healthy"] = False
                health_data["database"]["connection"] = "failed"
                health_data["database"]["error"] = str(db_error)
                health_data["status"] = "unhealthy"
                if health_data.get("issues") is None:
                    health_data["issues"] = []
                health_data["issues"].append(f"Database connection failed: {str(db_error)}")

        # Determine HTTP status code based on health status
        if health_data["status"] == "unhealthy":
            return JSONResponse(
                content=health_data,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        elif health_data["status"] == "degraded":
            return JSONResponse(
                content=health_data,
                status_code=status.HTTP_200_OK  # Still return 200 for degraded
            )

        return health_data

    except Exception as e:
        logger.error(f"Failed to generate health check: {e}")
        return JSONResponse(
            content={
                "status": "unhealthy",
                "error": str(e),
                "message": "Failed to generate health check"
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@router.get(
    "/metrics/stats",
    summary="JSON Statistics Summary",
    description="Get a JSON summary of all application metrics",
    response_class=JSONResponse,
    tags=["monitoring"]
)
async def get_stats_summary():
    """
    Get a JSON-format summary of all metrics.

    Provides a comprehensive overview of application metrics including:
    - Application information (name, version, uptime)
    - Request statistics (total, per second, by method, by status code)
    - Response time statistics (average, min, max)
    - Database query statistics
    - Top endpoints by request count
    - Endpoints with highest error rates
    - Slowest endpoints

    Returns:
        JSON object with comprehensive metrics summary
    """
    try:
        stats = metrics_collector.get_stats_summary()
        return stats
    except Exception as e:
        logger.error(f"Failed to generate stats summary: {e}")
        return JSONResponse(
            content={
                "error": str(e),
                "message": "Failed to generate stats summary"
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.get(
    "/metrics/ready",
    summary="Readiness Check",
    description="Simple readiness probe for Kubernetes/container orchestration",
    tags=["monitoring"]
)
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """
    Kubernetes-style readiness probe.

    Checks if the application is ready to receive traffic by verifying:
    - Application is running
    - Database is accessible

    Returns 200 if ready, 503 if not ready.
    """
    try:
        # Check database connectivity
        result = await db.execute(text("SELECT 1"))
        result.scalar()

        return {"status": "ready"}

    except Exception as e:
        logger.warning(f"Readiness check failed: {e}")
        return JSONResponse(
            content={"status": "not_ready", "reason": str(e)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@router.get(
    "/metrics/live",
    summary="Liveness Check",
    description="Simple liveness probe for Kubernetes/container orchestration",
    tags=["monitoring"]
)
async def liveness_check():
    """
    Kubernetes-style liveness probe.

    Simply returns 200 to indicate the application is alive.
    This endpoint should be as lightweight as possible.
    """
    return {"status": "alive"}


@router.get(
    "/metrics/info",
    summary="Application Info",
    description="Get basic application information",
    tags=["monitoring"]
)
async def get_app_info():
    """
    Get basic application information.

    Returns:
        Application name, version, environment, and feature flags
    """
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": getattr(settings, "ENVIRONMENT", "production"),
        "debug": settings.DEBUG,
        "features": {
            "prometheus_metrics": PROMETHEUS_AVAILABLE,
            "notifications_enabled": getattr(settings, "NOTIFICATION_ENABLED", False),
            "email_configured": getattr(settings, "email_enabled", False),
            "sms_configured": getattr(settings, "sms_enabled", False)
        }
    }
