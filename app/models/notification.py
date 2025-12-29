"""
Notification Models

Defines notification preferences for users and tenants, plus notification history tracking.
"""

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class NotificationEventType(str, enum.Enum):
    """Types of events that can trigger notifications."""
    TICKET_CREATED = "ticket_created"
    TICKET_ASSIGNED = "ticket_assigned"
    TICKET_STATUS_CHANGED = "ticket_status_changed"
    TICKET_COMMENT_ADDED = "ticket_comment_added"
    SLA_BREACH = "sla_breach"
    SLA_WARNING = "sla_warning"
    WORKLOG_ADDED = "worklog_added"
    ASSIGNMENT_DUE = "assignment_due"


class NotificationChannel(str, enum.Enum):
    """Channels through which notifications can be sent."""
    EMAIL = "email"
    SMS = "sms"
    IN_APP = "in_app"


class NotificationStatus(str, enum.Enum):
    """Status of notification delivery."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UserNotificationPreference(Base):
    """User-level notification preferences."""
    __tablename__ = "user_notification_preferences"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    # Global toggles
    email_enabled = Column(Boolean, default=True, nullable=False)
    sms_enabled = Column(Boolean, default=True, nullable=False)
    in_app_enabled = Column(Boolean, default=True, nullable=False)

    # Event-specific email preferences
    email_on_ticket_created = Column(Boolean, default=True, nullable=False)
    email_on_ticket_assigned = Column(Boolean, default=True, nullable=False)
    email_on_ticket_status_changed = Column(Boolean, default=True, nullable=False)
    email_on_ticket_comment = Column(Boolean, default=True, nullable=False)
    email_on_sla_breach = Column(Boolean, default=True, nullable=False)
    email_on_sla_warning = Column(Boolean, default=True, nullable=False)
    email_on_worklog_added = Column(Boolean, default=False, nullable=False)
    email_on_assignment_due = Column(Boolean, default=True, nullable=False)

    # Event-specific SMS preferences
    sms_on_ticket_created = Column(Boolean, default=False, nullable=False)
    sms_on_ticket_assigned = Column(Boolean, default=True, nullable=False)
    sms_on_ticket_status_changed = Column(Boolean, default=False, nullable=False)
    sms_on_ticket_comment = Column(Boolean, default=False, nullable=False)
    sms_on_sla_breach = Column(Boolean, default=True, nullable=False)
    sms_on_sla_warning = Column(Boolean, default=False, nullable=False)
    sms_on_worklog_added = Column(Boolean, default=False, nullable=False)
    sms_on_assignment_due = Column(Boolean, default=True, nullable=False)

    # Quiet hours (UTC)
    quiet_hours_enabled = Column(Boolean, default=False, nullable=False)
    quiet_hours_start = Column(String)  # Format: "HH:MM"
    quiet_hours_end = Column(String)  # Format: "HH:MM"

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", backref="notification_preference")


class TenantNotificationSettings(Base):
    """Tenant-level notification settings and defaults."""
    __tablename__ = "tenant_notification_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, unique=True, index=True)

    # Global tenant toggles (override user preferences if disabled)
    email_notifications_enabled = Column(Boolean, default=True, nullable=False)
    sms_notifications_enabled = Column(Boolean, default=True, nullable=False)

    # Custom from email/name for this tenant
    custom_from_email = Column(String)
    custom_from_name = Column(String)

    # Default preferences for new users (JSON blob)
    default_user_preferences = Column(JSON)

    # Notification throttling settings
    throttle_enabled = Column(Boolean, default=True, nullable=False)
    max_notifications_per_hour = Column(String, default="100")  # Per user

    # SLA warning threshold (minutes before breach to send warning)
    sla_warning_threshold_minutes = Column(String, default="30")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", backref="notification_settings")


class NotificationLog(Base):
    """Log of sent notifications for auditing and debugging."""
    __tablename__ = "notification_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Target
    user_id = Column(String, ForeignKey("users.id"), index=True)
    recipient_email = Column(String, index=True)
    recipient_phone = Column(String)

    # Notification details
    event_type = Column(SQLEnum(NotificationEventType), nullable=False, index=True)
    channel = Column(SQLEnum(NotificationChannel), nullable=False, index=True)
    status = Column(SQLEnum(NotificationStatus), nullable=False, default=NotificationStatus.PENDING, index=True)

    # Content
    subject = Column(String)
    body_text = Column(Text)
    body_html = Column(Text)

    # Related entity
    related_ticket_id = Column(String, ForeignKey("tickets.id"), index=True)
    related_entity_type = Column(String)  # ticket, assignment, worklog, etc.
    related_entity_id = Column(String)

    # Delivery metadata
    provider = Column(String)  # smtp, twilio, aws_sns
    provider_message_id = Column(String)  # External message ID from provider
    error_message = Column(Text)
    retry_count = Column(String, default="0")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    sent_at = Column(DateTime)
    delivered_at = Column(DateTime)
    failed_at = Column(DateTime)

    # Relationships
    tenant = relationship("Tenant")
    user = relationship("User")
    ticket = relationship("Ticket", foreign_keys=[related_ticket_id])
