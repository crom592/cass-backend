"""
Event Publisher Service.

Publishes events to SSE connections for real-time updates.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from app.core.sse import connection_manager
from app.models.ticket import Ticket, TicketStatus
from app.models.assignment import Assignment
from app.models.worklog import Worklog

logger = logging.getLogger(__name__)


class EventPublisher:
    """
    Service for publishing events to SSE connections.

    Provides methods for publishing various types of events:
    - Ticket events (created, updated, status changed)
    - Assignment events
    - Worklog events
    - User notifications
    """

    @staticmethod
    def _serialize_ticket(ticket: Ticket) -> Dict[str, Any]:
        """Serialize a ticket for event payload."""
        return {
            "id": ticket.id,
            "tenant_id": ticket.tenant_id,
            "site_id": ticket.site_id,
            "charger_id": ticket.charger_id,
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "description": ticket.description,
            "channel": ticket.channel.value if ticket.channel else None,
            "category": ticket.category.value if ticket.category else None,
            "priority": ticket.priority.value if ticket.priority else None,
            "current_status": ticket.current_status.value if ticket.current_status else None,
            "reporter_name": ticket.reporter_name,
            "reporter_email": ticket.reporter_email,
            "reporter_phone": ticket.reporter_phone,
            "opened_at": ticket.opened_at.isoformat() if ticket.opened_at else None,
            "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            "created_by": ticket.created_by,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
            "sla_breached": ticket.sla_breached,
            "resolution_summary": ticket.resolution_summary,
        }

    @staticmethod
    def _serialize_assignment(assignment: Assignment) -> Dict[str, Any]:
        """Serialize an assignment for event payload."""
        return {
            "id": assignment.id,
            "ticket_id": assignment.ticket_id,
            "assignee_type": assignment.assignee_type.value if assignment.assignee_type else None,
            "assignee_user_id": assignment.assignee_user_id,
            "assignee_vendor_name": assignment.assignee_vendor_name,
            "assignee_vendor_contact": assignment.assignee_vendor_contact,
            "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
            "started_at": assignment.started_at.isoformat() if assignment.started_at else None,
            "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
            "notes": assignment.notes,
            "assigned_by": assignment.assigned_by,
            "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
        }

    @staticmethod
    def _serialize_worklog(worklog: Worklog) -> Dict[str, Any]:
        """Serialize a worklog for event payload."""
        return {
            "id": worklog.id,
            "ticket_id": worklog.ticket_id,
            "body": worklog.body,
            "work_type": worklog.work_type.value if worklog.work_type else None,
            "time_spent_minutes": worklog.time_spent_minutes,
            "is_internal": worklog.is_internal,
            "author_id": worklog.author_id,
            "created_at": worklog.created_at.isoformat() if worklog.created_at else None,
            "updated_at": worklog.updated_at.isoformat() if worklog.updated_at else None,
        }

    @staticmethod
    async def publish_ticket_created(
        ticket: Ticket,
        created_by_user_id: Optional[str] = None
    ):
        """
        Publish a ticket created event.

        Args:
            ticket: The created ticket
            created_by_user_id: Optional user ID to exclude from broadcast
        """
        try:
            event_data = {
                "ticket": EventPublisher._serialize_ticket(ticket),
                "timestamp": datetime.utcnow().isoformat(),
            }

            await connection_manager.broadcast_to_tenant(
                tenant_id=ticket.tenant_id,
                event_type="ticket_created",
                data=event_data,
                exclude_user_id=created_by_user_id
            )

            logger.info(f"Published ticket_created event: {ticket.ticket_number}")

        except Exception as e:
            logger.error(f"Failed to publish ticket_created event: {e}")

    @staticmethod
    async def publish_ticket_updated(
        ticket: Ticket,
        updated_fields: Optional[Dict[str, Any]] = None,
        updated_by_user_id: Optional[str] = None
    ):
        """
        Publish a ticket updated event.

        Args:
            ticket: The updated ticket
            updated_fields: Optional dict of fields that were updated
            updated_by_user_id: Optional user ID to exclude from broadcast
        """
        try:
            event_data = {
                "ticket": EventPublisher._serialize_ticket(ticket),
                "updated_fields": updated_fields or {},
                "timestamp": datetime.utcnow().isoformat(),
            }

            await connection_manager.broadcast_to_tenant(
                tenant_id=ticket.tenant_id,
                event_type="ticket_updated",
                data=event_data,
                exclude_user_id=updated_by_user_id
            )

            logger.info(f"Published ticket_updated event: {ticket.ticket_number}")

        except Exception as e:
            logger.error(f"Failed to publish ticket_updated event: {e}")

    @staticmethod
    async def publish_ticket_status_changed(
        ticket: Ticket,
        old_status: TicketStatus,
        new_status: TicketStatus,
        changed_by_user_id: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """
        Publish a ticket status changed event.

        Args:
            ticket: The ticket whose status changed
            old_status: The previous status
            new_status: The new status
            changed_by_user_id: Optional user ID to exclude from broadcast
            reason: Optional reason for the status change
        """
        try:
            event_data = {
                "ticket": EventPublisher._serialize_ticket(ticket),
                "old_status": old_status.value if old_status else None,
                "new_status": new_status.value if new_status else None,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
            }

            await connection_manager.broadcast_to_tenant(
                tenant_id=ticket.tenant_id,
                event_type="ticket_status_changed",
                data=event_data,
                exclude_user_id=changed_by_user_id
            )

            logger.info(
                f"Published ticket_status_changed event: {ticket.ticket_number} "
                f"({old_status} -> {new_status})"
            )

        except Exception as e:
            logger.error(f"Failed to publish ticket_status_changed event: {e}")

    @staticmethod
    async def publish_assignment(
        assignment: Assignment,
        ticket: Ticket,
        assigned_by_user_id: Optional[str] = None
    ):
        """
        Publish an assignment event.

        Args:
            assignment: The assignment that was created
            ticket: The ticket that was assigned
            assigned_by_user_id: Optional user ID to exclude from broadcast
        """
        try:
            event_data = {
                "assignment": EventPublisher._serialize_assignment(assignment),
                "ticket": EventPublisher._serialize_ticket(ticket),
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Broadcast to tenant
            await connection_manager.broadcast_to_tenant(
                tenant_id=ticket.tenant_id,
                event_type="ticket_assigned",
                data=event_data,
                exclude_user_id=assigned_by_user_id
            )

            # Also send notification to assigned user if it's a user assignment
            if assignment.assignee_user_id:
                notification_data = {
                    "type": "assignment",
                    "title": "New Ticket Assignment",
                    "message": f"You have been assigned to ticket {ticket.ticket_number}: {ticket.title}",
                    "ticket_id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                await connection_manager.send_to_user(
                    user_id=assignment.assignee_user_id,
                    event_type="notification",
                    data=notification_data
                )

            logger.info(
                f"Published ticket_assigned event: {ticket.ticket_number} "
                f"-> {assignment.assignee_user_id or assignment.assignee_vendor_name}"
            )

        except Exception as e:
            logger.error(f"Failed to publish assignment event: {e}")

    @staticmethod
    async def publish_worklog(
        worklog: Worklog,
        ticket: Ticket,
        author_user_id: Optional[str] = None
    ):
        """
        Publish a worklog event.

        Args:
            worklog: The worklog that was created
            ticket: The ticket the worklog belongs to
            author_user_id: Optional user ID to exclude from broadcast
        """
        try:
            event_data = {
                "worklog": EventPublisher._serialize_worklog(worklog),
                "ticket": {
                    "id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "title": ticket.title,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            await connection_manager.broadcast_to_tenant(
                tenant_id=ticket.tenant_id,
                event_type="worklog_added",
                data=event_data,
                exclude_user_id=author_user_id
            )

            logger.info(f"Published worklog_added event: {ticket.ticket_number}")

        except Exception as e:
            logger.error(f"Failed to publish worklog event: {e}")

    @staticmethod
    async def publish_notification(
        user_id: str,
        notification_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ):
        """
        Publish a notification to a specific user.

        Args:
            user_id: The user to notify
            notification_type: Type of notification (e.g., 'info', 'warning', 'success')
            title: Notification title
            message: Notification message
            data: Optional additional data
        """
        try:
            notification_data = {
                "type": notification_type,
                "title": title,
                "message": message,
                "data": data or {},
                "timestamp": datetime.utcnow().isoformat(),
            }

            await connection_manager.send_to_user(
                user_id=user_id,
                event_type="notification",
                data=notification_data
            )

            logger.info(f"Published notification to user {user_id}: {title}")

        except Exception as e:
            logger.error(f"Failed to publish notification: {e}")


# Create a singleton instance
event_publisher = EventPublisher()
