"""
Prometheus-compatible metrics service for CASS backend.

Provides metrics collection and export for monitoring request counts,
response times, error rates, and active connections.
"""

import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta
import logging

try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY,
        CollectorRegistry,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Define stub classes if prometheus_client is not installed
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass

    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def observe(self, *args, **kwargs): pass

    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def set(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass

    class Info:
        def __init__(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass

    def generate_latest(*args, **kwargs): return b""
    CONTENT_TYPE_LATEST = "text/plain"
    REGISTRY = None

from app.core.config import settings

logger = logging.getLogger(__name__)


# Define histogram buckets for response times (in seconds)
RESPONSE_TIME_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0
)

# Define histogram buckets for database query times (in seconds)
DB_QUERY_TIME_BUCKETS = (
    0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5
)


@dataclass
class RequestStats:
    """Statistics for a single endpoint."""
    total_requests: int = 0
    total_errors: int = 0
    total_duration_seconds: float = 0.0
    min_duration_seconds: float = float("inf")
    max_duration_seconds: float = 0.0
    status_codes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    last_request_time: Optional[datetime] = None

    def record(self, duration_seconds: float, status_code: int):
        self.total_requests += 1
        self.total_duration_seconds += duration_seconds
        self.min_duration_seconds = min(self.min_duration_seconds, duration_seconds)
        self.max_duration_seconds = max(self.max_duration_seconds, duration_seconds)
        self.status_codes[status_code] += 1
        self.last_request_time = datetime.utcnow()

        if status_code >= 500:
            self.total_errors += 1

    @property
    def avg_duration_seconds(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_duration_seconds / self.total_requests

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": round(self.error_rate, 4),
            "avg_duration_ms": round(self.avg_duration_seconds * 1000, 2),
            "min_duration_ms": round(self.min_duration_seconds * 1000, 2) if self.min_duration_seconds != float("inf") else 0,
            "max_duration_ms": round(self.max_duration_seconds * 1000, 2),
            "status_codes": dict(self.status_codes),
            "last_request_time": self.last_request_time.isoformat() if self.last_request_time else None
        }


class MetricsCollector:
    """
    Collects and manages application metrics.

    Provides both Prometheus-compatible metrics export and internal
    statistics tracking for JSON-based endpoints.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = datetime.utcnow()

        # Internal statistics storage
        self._endpoint_stats: Dict[str, RequestStats] = defaultdict(RequestStats)
        self._method_stats: Dict[str, RequestStats] = defaultdict(RequestStats)
        self._global_stats = RequestStats()

        # Database query statistics
        self._db_query_count: int = 0
        self._db_query_duration_seconds: float = 0.0

        # Active connections tracking
        self._active_connections: int = 0

        # Initialize Prometheus metrics
        self._init_prometheus_metrics()

        logger.info(
            f"MetricsCollector initialized (Prometheus available: {PROMETHEUS_AVAILABLE})"
        )

    def _init_prometheus_metrics(self):
        """Initialize Prometheus metric collectors."""
        # Application info
        self.app_info = Info(
            "cass_app",
            "CASS application information"
        )
        if PROMETHEUS_AVAILABLE:
            self.app_info.info({
                "version": settings.APP_VERSION,
                "environment": getattr(settings, "ENVIRONMENT", "production"),
                "app_name": settings.APP_NAME
            })

        # Request counter
        self.request_counter = Counter(
            "cass_http_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status_code"]
        )

        # Request duration histogram
        self.request_duration = Histogram(
            "cass_http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=RESPONSE_TIME_BUCKETS
        )

        # Error counter
        self.error_counter = Counter(
            "cass_http_errors_total",
            "Total number of HTTP errors (5xx)",
            ["method", "endpoint", "status_code"]
        )

        # Active connections gauge
        self.active_connections_gauge = Gauge(
            "cass_active_connections",
            "Number of active HTTP connections"
        )

        # Database query counter
        self.db_query_counter = Counter(
            "cass_db_queries_total",
            "Total number of database queries"
        )

        # Database query duration histogram
        self.db_query_duration = Histogram(
            "cass_db_query_duration_seconds",
            "Database query duration in seconds",
            buckets=DB_QUERY_TIME_BUCKETS
        )

        # Memory usage gauge
        self.memory_usage_gauge = Gauge(
            "cass_memory_usage_bytes",
            "Current memory usage in bytes"
        )

        # Uptime gauge
        self.uptime_gauge = Gauge(
            "cass_uptime_seconds",
            "Application uptime in seconds"
        )

    def record_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration_seconds: float,
        db_query_count: int = 0,
        db_query_duration_seconds: float = 0.0
    ):
        """
        Record metrics for a completed HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: Request path
            status_code: HTTP response status code
            duration_seconds: Request duration in seconds
            db_query_count: Number of database queries executed
            db_query_duration_seconds: Total database query time in seconds
        """
        # Normalize endpoint to avoid cardinality explosion
        normalized_endpoint = self._normalize_endpoint(endpoint)

        with self._lock:
            # Update internal statistics
            self._global_stats.record(duration_seconds, status_code)
            self._endpoint_stats[normalized_endpoint].record(duration_seconds, status_code)
            self._method_stats[method].record(duration_seconds, status_code)

            # Update database statistics
            self._db_query_count += db_query_count
            self._db_query_duration_seconds += db_query_duration_seconds

        # Update Prometheus metrics
        if PROMETHEUS_AVAILABLE:
            self.request_counter.labels(
                method=method,
                endpoint=normalized_endpoint,
                status_code=str(status_code)
            ).inc()

            self.request_duration.labels(
                method=method,
                endpoint=normalized_endpoint
            ).observe(duration_seconds)

            if status_code >= 500:
                self.error_counter.labels(
                    method=method,
                    endpoint=normalized_endpoint,
                    status_code=str(status_code)
                ).inc()

            if db_query_count > 0:
                self.db_query_counter.inc(db_query_count)

            if db_query_duration_seconds > 0:
                self.db_query_duration.observe(db_query_duration_seconds)

    def _normalize_endpoint(self, endpoint: str) -> str:
        """
        Normalize endpoint path to prevent label cardinality explosion.

        Replaces dynamic path segments (like IDs) with placeholders.
        """
        if not endpoint:
            return "/"

        # Split path into segments
        segments = endpoint.split("/")
        normalized = []

        for segment in segments:
            if not segment:
                continue
            # Check if segment looks like an ID (UUID, numeric, etc.)
            if self._is_dynamic_segment(segment):
                normalized.append("{id}")
            else:
                normalized.append(segment)

        return "/" + "/".join(normalized) if normalized else "/"

    def _is_dynamic_segment(self, segment: str) -> bool:
        """Check if a path segment is likely a dynamic value (ID, UUID, etc.)."""
        # Check for UUID pattern
        if len(segment) == 36 and segment.count("-") == 4:
            return True
        # Check for numeric ID
        if segment.isdigit():
            return True
        # Check for hexadecimal ID (MongoDB ObjectId, etc.)
        if len(segment) == 24 and all(c in "0123456789abcdef" for c in segment.lower()):
            return True
        return False

    def increment_active_connections(self):
        """Increment the active connections counter."""
        with self._lock:
            self._active_connections += 1
        if PROMETHEUS_AVAILABLE:
            self.active_connections_gauge.inc()

    def decrement_active_connections(self):
        """Decrement the active connections counter."""
        with self._lock:
            self._active_connections = max(0, self._active_connections - 1)
        if PROMETHEUS_AVAILABLE:
            self.active_connections_gauge.dec()

    def get_active_connections(self) -> int:
        """Get the current number of active connections."""
        with self._lock:
            return self._active_connections

    def update_memory_usage(self, memory_bytes: int):
        """Update the memory usage gauge."""
        if PROMETHEUS_AVAILABLE:
            self.memory_usage_gauge.set(memory_bytes)

    def get_prometheus_metrics(self) -> bytes:
        """Generate Prometheus-format metrics output."""
        if not PROMETHEUS_AVAILABLE:
            return b"# Prometheus client not installed\n"

        # Update uptime
        uptime = (datetime.utcnow() - self._start_time).total_seconds()
        self.uptime_gauge.set(uptime)

        return generate_latest(REGISTRY)

    def get_prometheus_content_type(self) -> str:
        """Get the content type for Prometheus metrics."""
        return CONTENT_TYPE_LATEST

    def get_stats_summary(self) -> Dict[str, Any]:
        """
        Get a JSON-serializable summary of all metrics.

        Returns a dictionary containing request counts, response times,
        error rates, and other statistics.
        """
        with self._lock:
            uptime_seconds = (datetime.utcnow() - self._start_time).total_seconds()

            # Calculate requests per second
            requests_per_second = (
                self._global_stats.total_requests / uptime_seconds
                if uptime_seconds > 0 else 0
            )

            # Get top endpoints by request count
            top_endpoints = sorted(
                [
                    {"endpoint": ep, **stats.to_dict()}
                    for ep, stats in self._endpoint_stats.items()
                ],
                key=lambda x: x["total_requests"],
                reverse=True
            )[:10]

            # Get endpoints with highest error rates
            error_endpoints = sorted(
                [
                    {"endpoint": ep, **stats.to_dict()}
                    for ep, stats in self._endpoint_stats.items()
                    if stats.total_errors > 0
                ],
                key=lambda x: x["error_rate"],
                reverse=True
            )[:5]

            # Get slowest endpoints
            slowest_endpoints = sorted(
                [
                    {"endpoint": ep, **stats.to_dict()}
                    for ep, stats in self._endpoint_stats.items()
                    if stats.total_requests > 0
                ],
                key=lambda x: x["avg_duration_ms"],
                reverse=True
            )[:5]

            return {
                "application": {
                    "name": settings.APP_NAME,
                    "version": settings.APP_VERSION,
                    "environment": getattr(settings, "ENVIRONMENT", "production"),
                    "uptime_seconds": round(uptime_seconds, 2),
                    "start_time": self._start_time.isoformat() + "Z"
                },
                "requests": {
                    "total": self._global_stats.total_requests,
                    "per_second": round(requests_per_second, 4),
                    "errors": self._global_stats.total_errors,
                    "error_rate": round(self._global_stats.error_rate, 4),
                    "avg_duration_ms": round(self._global_stats.avg_duration_seconds * 1000, 2),
                    "min_duration_ms": round(
                        self._global_stats.min_duration_seconds * 1000, 2
                    ) if self._global_stats.min_duration_seconds != float("inf") else 0,
                    "max_duration_ms": round(self._global_stats.max_duration_seconds * 1000, 2),
                    "by_method": {
                        method: stats.to_dict()
                        for method, stats in self._method_stats.items()
                    },
                    "by_status_code": dict(self._global_stats.status_codes)
                },
                "database": {
                    "total_queries": self._db_query_count,
                    "total_duration_seconds": round(self._db_query_duration_seconds, 4),
                    "avg_query_duration_ms": round(
                        (self._db_query_duration_seconds / self._db_query_count * 1000)
                        if self._db_query_count > 0 else 0, 2
                    )
                },
                "connections": {
                    "active": self._active_connections
                },
                "top_endpoints": top_endpoints,
                "error_endpoints": error_endpoints,
                "slowest_endpoints": slowest_endpoints,
                "prometheus_available": PROMETHEUS_AVAILABLE
            }

    def get_health_details(self) -> Dict[str, Any]:
        """
        Get detailed health check information.

        Returns comprehensive health status including database connectivity,
        memory usage, and component status.
        """
        import psutil
        import os

        with self._lock:
            uptime = datetime.utcnow() - self._start_time

            # Get memory info
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()

            # Get CPU info
            cpu_percent = process.cpu_percent(interval=0.1)

            # Calculate error rate for health status
            error_rate = self._global_stats.error_rate
            avg_response_time = self._global_stats.avg_duration_seconds * 1000

            # Determine health status
            health_status = "healthy"
            health_issues = []

            if error_rate > 0.1:  # More than 10% errors
                health_status = "degraded"
                health_issues.append(f"High error rate: {error_rate:.2%}")

            if avg_response_time > 500:  # Average response time > 500ms
                health_status = "degraded"
                health_issues.append(f"High average response time: {avg_response_time:.0f}ms")

            if memory_info.rss > 1024 * 1024 * 1024:  # More than 1GB
                health_status = "degraded"
                health_issues.append(f"High memory usage: {memory_info.rss / (1024*1024):.0f}MB")

            return {
                "status": health_status,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "uptime": {
                    "seconds": uptime.total_seconds(),
                    "human": str(uptime).split(".")[0]  # Remove microseconds
                },
                "system": {
                    "memory": {
                        "rss_bytes": memory_info.rss,
                        "rss_mb": round(memory_info.rss / (1024 * 1024), 2),
                        "vms_bytes": memory_info.vms,
                        "vms_mb": round(memory_info.vms / (1024 * 1024), 2)
                    },
                    "cpu_percent": round(cpu_percent, 2),
                    "open_files": len(process.open_files()),
                    "threads": process.num_threads()
                },
                "requests": {
                    "total": self._global_stats.total_requests,
                    "errors": self._global_stats.total_errors,
                    "error_rate": round(error_rate, 4),
                    "avg_response_time_ms": round(avg_response_time, 2)
                },
                "database": {
                    "queries": self._db_query_count,
                    "healthy": True  # Will be updated by actual DB check
                },
                "active_connections": self._active_connections,
                "issues": health_issues if health_issues else None,
                "prometheus_available": PROMETHEUS_AVAILABLE
            }

    def reset_stats(self):
        """Reset all internal statistics (for testing purposes)."""
        with self._lock:
            self._endpoint_stats.clear()
            self._method_stats.clear()
            self._global_stats = RequestStats()
            self._db_query_count = 0
            self._db_query_duration_seconds = 0.0
            self._start_time = datetime.utcnow()


# Global metrics collector instance
metrics_collector = MetricsCollector()
