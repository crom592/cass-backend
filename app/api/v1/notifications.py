"""
Notification API Endpoints

Provides REST API endpoints for notification preferences, settings, and testing.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Optional, List
from datetime import datetime
import logging

from app.core.config import settings
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User, UserRole
from app.models.notification import (
    NotificationEventType,
    NotificationChannel,
    NotificationStatus,
    UserNotificationPreference,
    TenantNotificationSettings,
    NotificationLog,
)
from app.services.notification_service import NotificationService
from app.schemas.notification import (
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    TenantNotificationSettingsResponse,
    TenantNotificationSettingsUpdate,
    NotificationLogResponse,
    NotificationLogListResponse,
    TestNotificationRequest,
    TestNotificationResponse,
    NotificationStatusResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Notification System Status
# ============================================================================

@router.get("/status", response_model=NotificationStatusResponse)
async def get_notification_status(
    current_user: User = Depends(get_current_user)
):
    """
    Get the current status of the notification system.

    Returns information about which notification channels are configured and enabled.
    """
    return NotificationStatusResponse(
        email_enabled=settings.email_enabled,
        sms_enabled=settings.sms_enabled,
        email_provider="smtp",
        sms_provider=settings.SMS_PROVIDER,
        email_configured=bool(settings.SMTP_HOST),
        sms_configured=settings.sms_enabled,
        notifications_enabled=settings.NOTIFICATION_ENABLED
    )


# ============================================================================
# User Notification Preferences
# ============================================================================

@router.get("/preferences", response_model=NotificationPreferenceResponse)
async def get_user_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current user's notification preferences.

    Creates default preferences if none exist.
    """
    notification_service = NotificationService(db)
    prefs = await notification_service.get_or_create_user_preferences(current_user.id)
    return prefs


@router.patch("/preferences", response_model=NotificationPreferenceResponse)
async def update_user_preferences(
    preference_update: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update the current user's notification preferences.

    Only provided fields will be updated; others remain unchanged.
    """
    notification_service = NotificationService(db)
    prefs = await notification_service.get_or_create_user_preferences(current_user.id)

    # Update only provided fields
    update_data = preference_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(prefs, field, value)

    prefs.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(prefs)

    logger.info(f"Updated notification preferences for user {current_user.id}")
    return prefs


@router.get("/preferences/{user_id}", response_model=NotificationPreferenceResponse)
async def get_user_preferences_by_id(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get notification preferences for a specific user (admin only).

    Requires ADMIN or TENANT_ADMIN role.
    """
    # Check authorization
    if current_user.role not in [UserRole.ADMIN, UserRole.TENANT_ADMIN]:
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view other users' preferences"
            )

    # Verify user exists and belongs to same tenant
    result = await db.execute(
        select(User).where(
            and_(
                User.id == user_id,
                User.tenant_id == current_user.tenant_id
            )
        )
    )
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    notification_service = NotificationService(db)
    prefs = await notification_service.get_or_create_user_preferences(user_id)
    return prefs


# ============================================================================
# Tenant Notification Settings (Admin Only)
# ============================================================================

@router.get("/settings/tenant", response_model=TenantNotificationSettingsResponse)
async def get_tenant_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get notification settings for the current tenant.

    Requires ADMIN or TENANT_ADMIN role.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.TENANT_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view tenant settings"
        )

    result = await db.execute(
        select(TenantNotificationSettings).where(
            TenantNotificationSettings.tenant_id == current_user.tenant_id
        )
    )
    settings_obj = result.scalar_one_or_none()

    if not settings_obj:
        # Create default settings
        settings_obj = TenantNotificationSettings(tenant_id=current_user.tenant_id)
        db.add(settings_obj)
        await db.commit()
        await db.refresh(settings_obj)

    return settings_obj


@router.patch("/settings/tenant", response_model=TenantNotificationSettingsResponse)
async def update_tenant_settings(
    settings_update: TenantNotificationSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update notification settings for the current tenant.

    Requires ADMIN or TENANT_ADMIN role.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.TENANT_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update tenant settings"
        )

    result = await db.execute(
        select(TenantNotificationSettings).where(
            TenantNotificationSettings.tenant_id == current_user.tenant_id
        )
    )
    settings_obj = result.scalar_one_or_none()

    if not settings_obj:
        settings_obj = TenantNotificationSettings(tenant_id=current_user.tenant_id)
        db.add(settings_obj)

    # Update only provided fields
    update_data = settings_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings_obj, field, value)

    settings_obj.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(settings_obj)

    logger.info(f"Updated tenant notification settings for tenant {current_user.tenant_id}")
    return settings_obj


# ============================================================================
# Test Notifications
# ============================================================================

@router.post("/test", response_model=TestNotificationResponse)
async def send_test_notification(
    request: TestNotificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a test notification to verify configuration.

    Can send test emails or SMS to the specified recipient.
    If no recipient is provided, sends to the current user's email/phone.
    """
    notification_service = NotificationService(db)

    # Determine recipient
    if request.channel == NotificationChannel.EMAIL:
        recipient = request.recipient_email or current_user.email
        if not recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No email address provided or configured"
            )
    elif request.channel == NotificationChannel.SMS:
        recipient = request.recipient_phone or current_user.phone
        if not recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No phone number provided or configured"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel: {request.channel.value}"
        )

    result = await notification_service.send_test_notification(
        channel=request.channel,
        recipient=recipient,
        subject=request.subject,
        message=request.message
    )

    # Log the test notification
    await notification_service.log_notification(
        tenant_id=current_user.tenant_id,
        event_type=NotificationEventType.TICKET_CREATED,  # Using as placeholder for test
        channel=request.channel,
        status=NotificationStatus.SENT if result["success"] else NotificationStatus.FAILED,
        recipient_email=recipient if request.channel == NotificationChannel.EMAIL else None,
        recipient_phone=recipient if request.channel == NotificationChannel.SMS else None,
        user_id=current_user.id,
        subject=request.subject or "Test Notification",
        body_text=request.message,
        provider=result.get("provider_message_id") and "smtp" if request.channel == NotificationChannel.EMAIL else settings.SMS_PROVIDER,
        provider_message_id=result.get("provider_message_id"),
        error_message=result.get("error")
    )

    return TestNotificationResponse(**result)


# ============================================================================
# Notification Logs
# ============================================================================

@router.get("/logs", response_model=NotificationLogListResponse)
async def list_notification_logs(
    event_type: Optional[NotificationEventType] = Query(None, description="Filter by event type"),
    channel: Optional[NotificationChannel] = Query(None, description="Filter by channel"),
    notification_status: Optional[NotificationStatus] = Query(None, alias="status", description="Filter by status"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    ticket_id: Optional[str] = Query(None, description="Filter by related ticket ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List notification logs for the current tenant.

    Supports filtering by event type, channel, status, user, and ticket.
    Requires ADMIN, TENANT_ADMIN, or AS_MANAGER role for full access.
    Regular users can only see their own notifications.
    """
    # Build query
    query = select(NotificationLog).where(
        NotificationLog.tenant_id == current_user.tenant_id
    )

    # Non-admin users can only see their own notifications
    if current_user.role not in [UserRole.ADMIN, UserRole.TENANT_ADMIN, UserRole.AS_MANAGER]:
        query = query.where(NotificationLog.user_id == current_user.id)
    elif user_id:
        query = query.where(NotificationLog.user_id == user_id)

    # Apply filters
    if event_type:
        query = query.where(NotificationLog.event_type == event_type)
    if channel:
        query = query.where(NotificationLog.channel == channel)
    if notification_status:
        query = query.where(NotificationLog.status == notification_status)
    if ticket_id:
        query = query.where(NotificationLog.related_ticket_id == ticket_id)

    # Get total count
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(NotificationLog.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    logs = result.scalars().all()

    return NotificationLogListResponse(
        logs=logs,
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/logs/{log_id}", response_model=NotificationLogResponse)
async def get_notification_log(
    log_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific notification log entry.
    """
    query = select(NotificationLog).where(
        and_(
            NotificationLog.id == log_id,
            NotificationLog.tenant_id == current_user.tenant_id
        )
    )

    # Non-admin users can only see their own notifications
    if current_user.role not in [UserRole.ADMIN, UserRole.TENANT_ADMIN, UserRole.AS_MANAGER]:
        query = query.where(NotificationLog.user_id == current_user.id)

    result = await db.execute(query)
    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification log not found"
        )

    return log


# ============================================================================
# Notification Statistics
# ============================================================================

@router.get("/statistics")
async def get_notification_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to include"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get notification statistics for the current tenant.

    Returns aggregate metrics for sent/failed notifications.
    Requires ADMIN or TENANT_ADMIN role.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.TENANT_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view notification statistics"
        )

    from datetime import timedelta
    from sqlalchemy import func

    period_start = datetime.utcnow() - timedelta(days=days)

    # Get counts by status
    status_counts = {}
    for notif_status in NotificationStatus:
        result = await db.execute(
            select(func.count(NotificationLog.id)).where(
                and_(
                    NotificationLog.tenant_id == current_user.tenant_id,
                    NotificationLog.created_at >= period_start,
                    NotificationLog.status == notif_status
                )
            )
        )
        status_counts[notif_status.value] = result.scalar() or 0

    # Get counts by channel
    channel_counts = {}
    for channel in NotificationChannel:
        result = await db.execute(
            select(func.count(NotificationLog.id)).where(
                and_(
                    NotificationLog.tenant_id == current_user.tenant_id,
                    NotificationLog.created_at >= period_start,
                    NotificationLog.channel == channel
                )
            )
        )
        channel_counts[channel.value] = result.scalar() or 0

    # Get counts by event type
    event_counts = {}
    for event_type in NotificationEventType:
        result = await db.execute(
            select(func.count(NotificationLog.id)).where(
                and_(
                    NotificationLog.tenant_id == current_user.tenant_id,
                    NotificationLog.created_at >= period_start,
                    NotificationLog.event_type == event_type
                )
            )
        )
        event_counts[event_type.value] = result.scalar() or 0

    total_sent = status_counts.get("sent", 0) + status_counts.get("delivered", 0)
    total_failed = status_counts.get("failed", 0)
    success_rate = (total_sent / (total_sent + total_failed) * 100) if (total_sent + total_failed) > 0 else 0

    return {
        "period_start": period_start.isoformat(),
        "period_end": datetime.utcnow().isoformat(),
        "total_notifications": sum(status_counts.values()),
        "by_status": status_counts,
        "by_channel": channel_counts,
        "by_event_type": event_counts,
        "success_rate_percentage": round(success_rate, 2)
    }


# ============================================================================
# Resend Failed Notifications
# ============================================================================

@router.post("/logs/{log_id}/resend", response_model=NotificationLogResponse)
async def resend_notification(
    log_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Resend a failed notification.

    Only failed notifications can be resent. Requires ADMIN or TENANT_ADMIN role.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.TENANT_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to resend notifications"
        )

    result = await db.execute(
        select(NotificationLog).where(
            and_(
                NotificationLog.id == log_id,
                NotificationLog.tenant_id == current_user.tenant_id
            )
        )
    )
    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification log not found"
        )

    if log.status != NotificationStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed notifications can be resent"
        )

    notification_service = NotificationService(db)

    # Resend based on channel
    if log.channel == NotificationChannel.EMAIL and log.recipient_email:
        email_result = await notification_service.send_email(
            to=log.recipient_email,
            subject=log.subject or "Notification",
            body=log.body_text or "",
            html_body=log.body_html
        )

        if email_result["success"]:
            log.status = NotificationStatus.SENT
            log.sent_at = datetime.utcnow()
            log.error_message = None
            log.retry_count = str(int(log.retry_count or "0") + 1)
        else:
            log.retry_count = str(int(log.retry_count or "0") + 1)
            log.error_message = email_result.get("error")

    elif log.channel == NotificationChannel.SMS and log.recipient_phone:
        sms_result = await notification_service.send_sms(
            phone_number=log.recipient_phone,
            message=log.body_text or ""
        )

        if sms_result["success"]:
            log.status = NotificationStatus.SENT
            log.sent_at = datetime.utcnow()
            log.error_message = None
            log.provider_message_id = sms_result.get("message_id")
            log.retry_count = str(int(log.retry_count or "0") + 1)
        else:
            log.retry_count = str(int(log.retry_count or "0") + 1)
            log.error_message = sms_result.get("error")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot resend: missing recipient information"
        )

    await db.commit()
    await db.refresh(log)

    return log
