"""
Notification Schemas

Pydantic schemas for notification API endpoints.
"""

from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from app.models.notification import NotificationEventType, NotificationChannel, NotificationStatus


# ============================================================================
# User Notification Preferences
# ============================================================================

class NotificationPreferenceBase(BaseModel):
    """Base schema for notification preferences."""
    email_enabled: bool = True
    sms_enabled: bool = True
    in_app_enabled: bool = True

    # Email preferences
    email_on_ticket_created: bool = True
    email_on_ticket_assigned: bool = True
    email_on_ticket_status_changed: bool = True
    email_on_ticket_comment: bool = True
    email_on_sla_breach: bool = True
    email_on_sla_warning: bool = True
    email_on_worklog_added: bool = False
    email_on_assignment_due: bool = True

    # SMS preferences
    sms_on_ticket_created: bool = False
    sms_on_ticket_assigned: bool = True
    sms_on_ticket_status_changed: bool = False
    sms_on_ticket_comment: bool = False
    sms_on_sla_breach: bool = True
    sms_on_sla_warning: bool = False
    sms_on_worklog_added: bool = False
    sms_on_assignment_due: bool = True

    # Quiet hours
    quiet_hours_enabled: bool = False
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None


class NotificationPreferenceCreate(NotificationPreferenceBase):
    """Schema for creating notification preferences."""
    pass


class NotificationPreferenceUpdate(BaseModel):
    """Schema for updating notification preferences (all fields optional)."""
    email_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None

    email_on_ticket_created: Optional[bool] = None
    email_on_ticket_assigned: Optional[bool] = None
    email_on_ticket_status_changed: Optional[bool] = None
    email_on_ticket_comment: Optional[bool] = None
    email_on_sla_breach: Optional[bool] = None
    email_on_sla_warning: Optional[bool] = None
    email_on_worklog_added: Optional[bool] = None
    email_on_assignment_due: Optional[bool] = None

    sms_on_ticket_created: Optional[bool] = None
    sms_on_ticket_assigned: Optional[bool] = None
    sms_on_ticket_status_changed: Optional[bool] = None
    sms_on_ticket_comment: Optional[bool] = None
    sms_on_sla_breach: Optional[bool] = None
    sms_on_sla_warning: Optional[bool] = None
    sms_on_worklog_added: Optional[bool] = None
    sms_on_assignment_due: Optional[bool] = None

    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None


class NotificationPreferenceResponse(NotificationPreferenceBase):
    """Response schema for notification preferences."""
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Tenant Notification Settings
# ============================================================================

class TenantNotificationSettingsBase(BaseModel):
    """Base schema for tenant notification settings."""
    email_notifications_enabled: bool = True
    sms_notifications_enabled: bool = True
    custom_from_email: Optional[str] = None
    custom_from_name: Optional[str] = None
    default_user_preferences: Optional[Dict[str, Any]] = None
    throttle_enabled: bool = True
    max_notifications_per_hour: str = "100"
    sla_warning_threshold_minutes: str = "30"


class TenantNotificationSettingsUpdate(BaseModel):
    """Schema for updating tenant notification settings."""
    email_notifications_enabled: Optional[bool] = None
    sms_notifications_enabled: Optional[bool] = None
    custom_from_email: Optional[str] = None
    custom_from_name: Optional[str] = None
    default_user_preferences: Optional[Dict[str, Any]] = None
    throttle_enabled: Optional[bool] = None
    max_notifications_per_hour: Optional[str] = None
    sla_warning_threshold_minutes: Optional[str] = None


class TenantNotificationSettingsResponse(TenantNotificationSettingsBase):
    """Response schema for tenant notification settings."""
    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Notification Log
# ============================================================================

class NotificationLogResponse(BaseModel):
    """Response schema for notification log entry."""
    id: str
    tenant_id: str
    user_id: Optional[str]
    recipient_email: Optional[str]
    recipient_phone: Optional[str]
    event_type: NotificationEventType
    channel: NotificationChannel
    status: NotificationStatus
    subject: Optional[str]
    related_ticket_id: Optional[str]
    related_entity_type: Optional[str]
    related_entity_id: Optional[str]
    provider: Optional[str]
    provider_message_id: Optional[str]
    error_message: Optional[str]
    retry_count: str
    created_at: datetime
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime]
    failed_at: Optional[datetime]

    class Config:
        from_attributes = True


class NotificationLogListResponse(BaseModel):
    """Response schema for list of notification logs."""
    logs: List[NotificationLogResponse]
    total: int
    skip: int
    limit: int


# ============================================================================
# Test Notification
# ============================================================================

class TestNotificationRequest(BaseModel):
    """Request schema for sending a test notification."""
    channel: NotificationChannel = NotificationChannel.EMAIL
    recipient_email: Optional[EmailStr] = None
    recipient_phone: Optional[str] = None
    subject: Optional[str] = Field(default="Test Notification from CASS")
    message: Optional[str] = Field(default="This is a test notification to verify your notification settings are working correctly.")


class TestNotificationResponse(BaseModel):
    """Response schema for test notification result."""
    success: bool
    channel: NotificationChannel
    recipient: str
    message: str
    provider_message_id: Optional[str] = None
    error: Optional[str] = None


# ============================================================================
# Notification Status
# ============================================================================

class NotificationStatusResponse(BaseModel):
    """Response schema for notification system status."""
    email_enabled: bool
    sms_enabled: bool
    email_provider: str
    sms_provider: str
    email_configured: bool
    sms_configured: bool
    notifications_enabled: bool


# ============================================================================
# Bulk Notification
# ============================================================================

class BulkNotificationRequest(BaseModel):
    """Request schema for sending bulk notifications."""
    event_type: NotificationEventType
    ticket_id: Optional[str] = None
    user_ids: Optional[List[str]] = None
    channels: List[NotificationChannel] = [NotificationChannel.EMAIL]
    custom_subject: Optional[str] = None
    custom_message: Optional[str] = None


class BulkNotificationResponse(BaseModel):
    """Response schema for bulk notification result."""
    total_recipients: int
    sent_count: int
    failed_count: int
    results: List[Dict[str, Any]]
