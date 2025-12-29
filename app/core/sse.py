"""
Server-Sent Events (SSE) Connection Manager.

Manages SSE connections for real-time updates to clients.
Supports per-tenant connection pools and targeted messaging.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from asyncio import Queue

logger = logging.getLogger(__name__)


@dataclass
class SSEConnection:
    """Represents a single SSE connection."""
    user_id: str
    tenant_id: str
    queue: Queue = field(default_factory=Queue)
    connected_at: datetime = field(default_factory=datetime.utcnow)

    def __hash__(self):
        return hash(id(self))

    def __eq__(self, other):
        return id(self) == id(other)


class ConnectionManager:
    """
    Manages SSE connections for the application.

    Supports:
    - Per-tenant connection pools
    - Broadcast to all connections in a tenant
    - Send to specific user connections
    - Connection health monitoring
    """

    def __init__(self):
        # tenant_id -> set of connections
        self._tenant_connections: Dict[str, Set[SSEConnection]] = {}
        # user_id -> set of connections (user can have multiple browser tabs)
        self._user_connections: Dict[str, Set[SSEConnection]] = {}
        # All connections for global broadcasts
        self._all_connections: Set[SSEConnection] = set()
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, tenant_id: str) -> SSEConnection:
        """
        Register a new SSE connection.

        Args:
            user_id: The user's ID
            tenant_id: The tenant's ID

        Returns:
            SSEConnection object for this connection
        """
        connection = SSEConnection(user_id=user_id, tenant_id=tenant_id)

        async with self._lock:
            # Add to tenant pool
            if tenant_id not in self._tenant_connections:
                self._tenant_connections[tenant_id] = set()
            self._tenant_connections[tenant_id].add(connection)

            # Add to user pool
            if user_id not in self._user_connections:
                self._user_connections[user_id] = set()
            self._user_connections[user_id].add(connection)

            # Add to global pool
            self._all_connections.add(connection)

        logger.info(
            f"SSE connection established: user={user_id}, tenant={tenant_id}, "
            f"total_connections={len(self._all_connections)}"
        )

        return connection

    async def disconnect(self, connection: SSEConnection):
        """
        Remove a connection from all pools.

        Args:
            connection: The connection to remove
        """
        async with self._lock:
            # Remove from tenant pool
            if connection.tenant_id in self._tenant_connections:
                self._tenant_connections[connection.tenant_id].discard(connection)
                if not self._tenant_connections[connection.tenant_id]:
                    del self._tenant_connections[connection.tenant_id]

            # Remove from user pool
            if connection.user_id in self._user_connections:
                self._user_connections[connection.user_id].discard(connection)
                if not self._user_connections[connection.user_id]:
                    del self._user_connections[connection.user_id]

            # Remove from global pool
            self._all_connections.discard(connection)

        logger.info(
            f"SSE connection closed: user={connection.user_id}, "
            f"tenant={connection.tenant_id}, "
            f"total_connections={len(self._all_connections)}"
        )

    async def broadcast_to_tenant(
        self,
        tenant_id: str,
        event_type: str,
        data: Any,
        exclude_user_id: Optional[str] = None
    ):
        """
        Broadcast an event to all connections in a tenant.

        Args:
            tenant_id: The tenant to broadcast to
            event_type: The type of event (e.g., 'ticket_created')
            data: The event data (will be JSON serialized)
            exclude_user_id: Optional user to exclude from broadcast
        """
        connections = self._tenant_connections.get(tenant_id, set())

        if not connections:
            logger.debug(f"No connections for tenant {tenant_id}")
            return

        message = self._format_sse_message(event_type, data)

        tasks = []
        for conn in connections:
            if exclude_user_id and conn.user_id == exclude_user_id:
                continue
            tasks.append(self._send_to_connection(conn, message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.debug(
                f"Broadcast to tenant {tenant_id}: event={event_type}, "
                f"recipients={len(tasks)}"
            )

    async def send_to_user(
        self,
        user_id: str,
        event_type: str,
        data: Any
    ):
        """
        Send an event to all connections for a specific user.

        Args:
            user_id: The user to send to
            event_type: The type of event
            data: The event data
        """
        connections = self._user_connections.get(user_id, set())

        if not connections:
            logger.debug(f"No connections for user {user_id}")
            return

        message = self._format_sse_message(event_type, data)

        tasks = [self._send_to_connection(conn, message) for conn in connections]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(
            f"Sent to user {user_id}: event={event_type}, "
            f"connections={len(tasks)}"
        )

    async def broadcast_global(self, event_type: str, data: Any):
        """
        Broadcast an event to all connections.

        Args:
            event_type: The type of event
            data: The event data
        """
        if not self._all_connections:
            return

        message = self._format_sse_message(event_type, data)

        tasks = [
            self._send_to_connection(conn, message)
            for conn in self._all_connections
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(
            f"Global broadcast: event={event_type}, "
            f"recipients={len(tasks)}"
        )

    async def _send_to_connection(self, connection: SSEConnection, message: str):
        """Send a message to a specific connection."""
        try:
            await connection.queue.put(message)
        except Exception as e:
            logger.error(f"Failed to send message to connection: {e}")

    def _format_sse_message(self, event_type: str, data: Any) -> str:
        """
        Format a message according to SSE specification.

        SSE format:
        event: event_type
        data: json_data

        """
        json_data = json.dumps(data, default=str)
        return f"event: {event_type}\ndata: {json_data}\n\n"

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            "total_connections": len(self._all_connections),
            "tenants": len(self._tenant_connections),
            "users": len(self._user_connections),
            "connections_by_tenant": {
                tid: len(conns)
                for tid, conns in self._tenant_connections.items()
            }
        }


# Global connection manager instance
connection_manager = ConnectionManager()


async def get_connection_manager() -> ConnectionManager:
    """Dependency to get the connection manager."""
    return connection_manager
