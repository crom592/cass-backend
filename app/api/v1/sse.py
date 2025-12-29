"""
Server-Sent Events (SSE) API Endpoints.

Provides real-time streaming endpoints for:
- Ticket updates
- User notifications
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.sse import connection_manager, SSEConnection
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_user_from_token(
    token: str,
    db: AsyncSession
) -> Optional[User]:
    """
    Validate token and get user.

    For SSE connections, we use query parameter auth instead of headers
    because EventSource doesn't support custom headers.
    """
    if not token:
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        return None

    return user


async def event_generator(connection: SSEConnection):
    """
    Generate SSE events for a connection.

    Yields events from the connection's queue.
    Sends heartbeat pings to keep connection alive.
    """
    try:
        while True:
            try:
                # Wait for message with timeout (for heartbeat)
                message = await asyncio.wait_for(
                    connection.queue.get(),
                    timeout=30.0
                )
                yield message
            except asyncio.TimeoutError:
                # Send heartbeat ping
                yield ": ping\n\n"
    except asyncio.CancelledError:
        # Connection was closed
        logger.debug(f"SSE generator cancelled for user {connection.user_id}")
        raise
    except Exception as e:
        logger.error(f"SSE generator error: {e}")
        raise


@router.get("/tickets")
async def stream_tickets(
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream ticket updates for the authenticated user's tenant.

    Events:
    - ticket_created: New ticket was created
    - ticket_updated: Ticket was modified
    - ticket_status_changed: Ticket status changed
    - ticket_assigned: Ticket was assigned

    Authentication is via query parameter 'token' since EventSource
    doesn't support custom headers.

    Example usage:
    ```javascript
    const eventSource = new EventSource('/api/v1/sse/tickets?token=your_jwt_token');

    eventSource.addEventListener('ticket_created', (event) => {
        const data = JSON.parse(event.data);
        console.log('New ticket:', data.ticket);
    });
    ```
    """
    # Authenticate user
    user = await get_user_from_token(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    # Create SSE connection
    connection = await connection_manager.connect(
        user_id=user.id,
        tenant_id=user.tenant_id
    )

    async def generate():
        try:
            # Send initial connection confirmation
            yield f"event: connected\ndata: {{\"user_id\": \"{user.id}\", \"tenant_id\": \"{user.tenant_id}\"}}\n\n"

            async for message in event_generator(connection):
                yield message
        finally:
            await connection_manager.disconnect(connection)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.get("/notifications")
async def stream_notifications(
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream user-specific notifications.

    Events:
    - notification: User notification (assignment, mention, etc.)

    Authentication is via query parameter 'token'.

    Example usage:
    ```javascript
    const eventSource = new EventSource('/api/v1/sse/notifications?token=your_jwt_token');

    eventSource.addEventListener('notification', (event) => {
        const data = JSON.parse(event.data);
        console.log('Notification:', data.title, data.message);
    });
    ```
    """
    # Authenticate user
    user = await get_user_from_token(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    # Create SSE connection
    connection = await connection_manager.connect(
        user_id=user.id,
        tenant_id=user.tenant_id
    )

    async def generate():
        try:
            # Send initial connection confirmation
            yield f"event: connected\ndata: {{\"user_id\": \"{user.id}\"}}\n\n"

            async for message in event_generator(connection):
                yield message
        finally:
            await connection_manager.disconnect(connection)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/stats")
async def get_sse_stats(
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get SSE connection statistics.

    Requires admin role.
    """
    # Authenticate user
    user = await get_user_from_token(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    # Check for admin role
    if user.role.value not in ["admin", "tenant_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    return connection_manager.get_stats()
