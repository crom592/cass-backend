from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
import time
import logging

logger = logging.getLogger(__name__)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware to log all API requests for audit purposes."""

    async def dispatch(self, request: Request, call_next):
        # Record request start time
        start_time = time.time()

        # Get request details
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log request (in production, this should write to AuditLog table)
        logger.info(
            f"API Request: {method} {path} - "
            f"Status: {response.status_code} - "
            f"Duration: {duration:.3f}s - "
            f"IP: {client_ip}"
        )

        # TODO: Write to AuditLog table in database
        # This would require extracting user info from JWT token
        # and writing structured audit logs to the database

        return response
