"""
Performance monitoring middleware for CASS backend.

Provides request timing, database query tracking, memory usage monitoring,
and slow query logging functionality.
"""

import time
import uuid
import tracemalloc
import logging
import json
from typing import Callable, Optional
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import settings

logger = logging.getLogger(__name__)

# Context variables for request-scoped data
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
db_metrics_ctx: ContextVar[Optional["DatabaseMetrics"]] = ContextVar("db_metrics", default=None)


@dataclass
class DatabaseMetrics:
    """Tracks database query metrics for a single request."""
    query_count: int = 0
    total_duration_ms: float = 0.0
    slow_queries: list = field(default_factory=list)

    def add_query(self, duration_ms: float, statement: str = ""):
        """Record a database query execution."""
        self.query_count += 1
        self.total_duration_ms += duration_ms

        # Track slow queries (> 100ms by default)
        slow_query_threshold = getattr(settings, "SLOW_QUERY_THRESHOLD_MS", 100)
        if duration_ms > slow_query_threshold:
            self.slow_queries.append({
                "duration_ms": round(duration_ms, 2),
                "statement": statement[:500] if statement else "",  # Truncate long statements
                "timestamp": datetime.utcnow().isoformat()
            })


class QueryTimer:
    """Context manager for timing database queries."""

    def __init__(self):
        self.start_time: Optional[float] = None
        self.statement: str = ""

    def start(self, statement: str = ""):
        self.start_time = time.perf_counter()
        self.statement = statement

    def stop(self):
        if self.start_time is None:
            return 0.0
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        self.start_time = None
        return duration_ms


# Global query timer storage (keyed by connection)
_query_timers: dict = {}


def setup_db_event_listeners(engine: Engine):
    """
    Set up SQLAlchemy event listeners for query timing.

    This function should be called once during application startup
    after the database engine is created.
    """

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn_id = id(conn)
        timer = QueryTimer()
        timer.start(statement)
        _query_timers[conn_id] = timer

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn_id = id(conn)
        timer = _query_timers.pop(conn_id, None)
        if timer:
            duration_ms = timer.stop()

            # Get current request's database metrics
            db_metrics = db_metrics_ctx.get()
            if db_metrics:
                db_metrics.add_query(duration_ms, statement)

            # Log slow queries
            slow_query_threshold = getattr(settings, "SLOW_QUERY_THRESHOLD_MS", 100)
            if duration_ms > slow_query_threshold:
                request_id = request_id_ctx.get() or "no-request"
                logger.warning(
                    f"Slow query detected",
                    extra={
                        "request_id": request_id,
                        "duration_ms": round(duration_ms, 2),
                        "statement": statement[:500],
                        "event_type": "slow_query"
                    }
                )

    logger.info("Database query timing listeners registered")


def get_memory_usage_mb() -> float:
    """Get current memory usage in megabytes."""
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # maxrss is in kilobytes on Linux, bytes on macOS
        import platform
        if platform.system() == "Darwin":
            return usage.ru_maxrss / (1024 * 1024)  # bytes to MB
        else:
            return usage.ru_maxrss / 1024  # KB to MB
    except ImportError:
        # Fallback for systems without resource module
        return 0.0


def get_request_id() -> Optional[str]:
    """Get the current request ID from context."""
    return request_id_ctx.get()


def get_db_metrics() -> Optional[DatabaseMetrics]:
    """Get the current request's database metrics from context."""
    return db_metrics_ctx.get()


class MonitoringMiddleware(BaseHTTPMiddleware):
    """
    Performance monitoring middleware.

    Features:
    - Request timing (total duration)
    - Request ID tracking
    - Database query counting and timing
    - Memory usage tracking
    - Slow request logging
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate unique request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_ctx.set(request_id)

        # Initialize database metrics for this request
        db_metrics = DatabaseMetrics()
        db_metrics_ctx.set(db_metrics)

        # Record start time and memory
        start_time = time.perf_counter()
        start_memory = get_memory_usage_mb()

        # Extract request details
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log exception with request context
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Request failed with exception",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(e),
                    "event_type": "request_error"
                }
            )
            raise

        # Calculate metrics
        duration_ms = (time.perf_counter() - start_time) * 1000
        end_memory = get_memory_usage_mb()
        memory_delta = end_memory - start_memory

        # Get database metrics
        db_metrics = db_metrics_ctx.get()
        query_count = db_metrics.query_count if db_metrics else 0
        query_duration_ms = db_metrics.total_duration_ms if db_metrics else 0.0
        slow_queries = db_metrics.slow_queries if db_metrics else []

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        # Get thresholds from settings
        slow_request_threshold = getattr(settings, "SLOW_REQUEST_THRESHOLD_MS", 1000)

        # Build log context
        log_context = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": client_ip,
            "db_query_count": query_count,
            "db_query_duration_ms": round(query_duration_ms, 2),
            "memory_usage_mb": round(end_memory, 2),
            "memory_delta_mb": round(memory_delta, 2),
            "event_type": "request_complete"
        }

        # Log slow requests with warning level
        if duration_ms > slow_request_threshold:
            log_context["slow_queries"] = slow_queries
            log_context["event_type"] = "slow_request"
            logger.warning(
                f"Slow request: {method} {path} took {duration_ms:.2f}ms",
                extra=log_context
            )
        else:
            # Normal request logging
            if settings.DEBUG or path.startswith("/api/"):
                logger.info(
                    f"Request: {method} {path} - {response.status_code} - {duration_ms:.2f}ms",
                    extra=log_context
                )

        # Update Prometheus metrics if available
        try:
            from app.services.metrics_service import metrics_collector
            metrics_collector.record_request(
                method=method,
                endpoint=path,
                status_code=response.status_code,
                duration_seconds=duration_ms / 1000,
                db_query_count=query_count,
                db_query_duration_seconds=query_duration_ms / 1000
            )
        except ImportError:
            pass  # Metrics service not yet loaded
        except Exception as e:
            logger.debug(f"Failed to record metrics: {e}")

        return response


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Outputs logs in JSON format for easy parsing by log aggregation systems.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add request ID if available
        request_id = request_id_ctx.get()
        if request_id:
            log_data["request_id"] = request_id

        # Add extra fields from the record
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in (
                    "name", "msg", "args", "created", "filename", "funcName",
                    "levelname", "levelno", "lineno", "module", "msecs",
                    "pathname", "process", "processName", "relativeCreated",
                    "stack_info", "exc_info", "exc_text", "thread", "threadName",
                    "message", "taskName"
                ):
                    log_data[key] = value

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


def configure_structured_logging(log_level: str = "INFO", json_format: bool = True):
    """
    Configure application-wide structured logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: If True, use JSON formatting; otherwise use standard format
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if json_format:
        console_handler.setFormatter(StructuredJsonFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] %(message)s",
                defaults={"request_id": "no-request"}
            )
        )

    root_logger.addHandler(console_handler)

    # Set specific logger levels
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if settings.DEBUG else logging.WARNING
    )

    logger.info("Structured logging configured", extra={"json_format": json_format})
