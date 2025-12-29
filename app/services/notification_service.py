"""
Notification Service Module

Provides email and SMS notification functionality for the CASS system.
Supports multiple SMS providers (Twilio, AWS SNS) and async email sending via aiosmtplib.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.notification import (
    NotificationEventType,
    NotificationChannel,
    NotificationStatus,
    UserNotificationPreference,
    TenantNotificationSettings,
    NotificationLog,
)
from app.models.user import User
from app.models.ticket import Ticket
from app.models.worklog import Worklog
from app.models.assignment import Assignment


logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


# ============================================================================
# SMS Provider Interface and Implementations
# ============================================================================

class SMSProvider(ABC):
    """Abstract base class for SMS providers."""

    @abstractmethod
    async def send_sms(
        self,
        phone_number: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send an SMS message.

        Args:
            phone_number: Recipient phone number in E.164 format
            message: Message content

        Returns:
            Dictionary with 'success', 'message_id', and optionally 'error'
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the provider is properly configured."""
        pass


class TwilioSMSProvider(SMSProvider):
    """Twilio SMS provider implementation."""

    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_number = settings.TWILIO_FROM_NUMBER or settings.SMS_FROM_NUMBER
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)

    async def send_sms(
        self,
        phone_number: str,
        message: str
    ) -> Dict[str, Any]:
        """Send SMS via Twilio."""
        if not self.is_configured():
            return {
                "success": False,
                "message_id": None,
                "error": "Twilio is not configured"
            }

        try:
            # Import twilio only when needed
            from twilio.rest import Client
            from twilio.base.exceptions import TwilioRestException

            if self._client is None:
                self._client = Client(self.account_sid, self.auth_token)

            # Twilio's Python client is synchronous, run in executor
            import asyncio
            loop = asyncio.get_event_loop()

            def send_sync():
                return self._client.messages.create(
                    body=message,
                    from_=self.from_number,
                    to=phone_number
                )

            twilio_message = await loop.run_in_executor(None, send_sync)

            logger.info(f"Twilio SMS sent successfully: {twilio_message.sid}")
            return {
                "success": True,
                "message_id": twilio_message.sid,
                "error": None
            }

        except ImportError:
            logger.error("Twilio package not installed. Install with: pip install twilio")
            return {
                "success": False,
                "message_id": None,
                "error": "Twilio package not installed"
            }
        except Exception as e:
            logger.error(f"Twilio SMS send failed: {str(e)}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }


class AWSSNSProvider(SMSProvider):
    """AWS SNS SMS provider implementation."""

    def __init__(self):
        self.region = settings.AWS_SNS_REGION or settings.AWS_REGION
        self.access_key = settings.AWS_SNS_ACCESS_KEY or settings.AWS_ACCESS_KEY_ID
        self.secret_key = settings.AWS_SNS_SECRET_KEY or settings.AWS_SECRET_ACCESS_KEY
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.region and self.access_key and self.secret_key)

    async def send_sms(
        self,
        phone_number: str,
        message: str
    ) -> Dict[str, Any]:
        """Send SMS via AWS SNS."""
        if not self.is_configured():
            return {
                "success": False,
                "message_id": None,
                "error": "AWS SNS is not configured"
            }

        try:
            # Import boto3 only when needed
            import boto3
            from botocore.exceptions import ClientError
            import asyncio

            if self._client is None:
                self._client = boto3.client(
                    'sns',
                    region_name=self.region,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key
                )

            loop = asyncio.get_event_loop()

            def send_sync():
                return self._client.publish(
                    PhoneNumber=phone_number,
                    Message=message,
                    MessageAttributes={
                        'AWS.SNS.SMS.SMSType': {
                            'DataType': 'String',
                            'StringValue': 'Transactional'
                        }
                    }
                )

            response = await loop.run_in_executor(None, send_sync)
            message_id = response.get('MessageId')

            logger.info(f"AWS SNS SMS sent successfully: {message_id}")
            return {
                "success": True,
                "message_id": message_id,
                "error": None
            }

        except ImportError:
            logger.error("boto3 package not installed. Install with: pip install boto3")
            return {
                "success": False,
                "message_id": None,
                "error": "boto3 package not installed"
            }
        except Exception as e:
            logger.error(f"AWS SNS SMS send failed: {str(e)}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }


def get_sms_provider() -> SMSProvider:
    """Factory function to get the configured SMS provider."""
    provider_name = settings.SMS_PROVIDER.lower()

    if provider_name == "twilio":
        return TwilioSMSProvider()
    elif provider_name == "aws_sns":
        return AWSSNSProvider()
    else:
        logger.warning(f"Unknown SMS provider: {provider_name}, defaulting to Twilio")
        return TwilioSMSProvider()


# ============================================================================
# Notification Service
# ============================================================================

class NotificationService:
    """
    Service for managing notifications across email and SMS channels.

    Provides methods for:
    - Sending email notifications
    - Sending SMS notifications
    - Event-based notifications (ticket created, assigned, etc.)
    - User preference management
    - Notification logging
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the notification service.

        Args:
            db: Async database session
        """
        self.db = db
        self.sms_provider = get_sms_provider()

        # Initialize Jinja2 template environment
        self.template_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(['html', 'xml'])
        )

    # ========================================================================
    # Email Methods
    # ========================================================================

    async def send_email(
        self,
        to: Union[str, List[str]],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Send an email using async SMTP.

        Args:
            to: Recipient email address(es)
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body
            from_email: Optional sender email (defaults to config)
            from_name: Optional sender name (defaults to config)
            reply_to: Optional reply-to address
            cc: Optional CC recipients
            bcc: Optional BCC recipients

        Returns:
            Dictionary with 'success', 'message_id', and optionally 'error'
        """
        if not settings.NOTIFICATION_ENABLED:
            logger.debug("Notifications are disabled")
            return {"success": False, "message_id": None, "error": "Notifications disabled"}

        if not settings.email_enabled:
            logger.warning("Email is not configured")
            return {"success": False, "message_id": None, "error": "Email not configured"}

        # Normalize recipients to list
        recipients = [to] if isinstance(to, str) else to

        # Build email message
        sender_email = from_email or settings.SMTP_FROM_EMAIL or settings.SMTP_USER
        sender_name = from_name or settings.SMTP_FROM_NAME

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
        message["To"] = ", ".join(recipients)

        if reply_to:
            message["Reply-To"] = reply_to
        if cc:
            message["Cc"] = ", ".join(cc)

        # Attach plain text and HTML parts
        message.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            message.attach(MIMEText(html_body, "html", "utf-8"))

        # Calculate all recipients for sending
        all_recipients = recipients.copy()
        if cc:
            all_recipients.extend(cc)
        if bcc:
            all_recipients.extend(bcc)

        try:
            # Send email via aiosmtplib
            smtp_kwargs = {
                "hostname": settings.SMTP_HOST,
                "port": settings.SMTP_PORT,
                "timeout": settings.SMTP_TIMEOUT,
            }

            if settings.SMTP_USE_SSL:
                smtp_kwargs["use_tls"] = True
            elif settings.SMTP_USE_TLS:
                smtp_kwargs["start_tls"] = True

            async with aiosmtplib.SMTP(**smtp_kwargs) as smtp:
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

                response = await smtp.send_message(message, recipients=all_recipients)

            logger.info(f"Email sent successfully to {recipients}")
            return {
                "success": True,
                "message_id": message.get("Message-ID"),
                "error": None
            }

        except aiosmtplib.SMTPException as e:
            logger.error(f"SMTP error sending email: {str(e)}")
            return {
                "success": False,
                "message_id": None,
                "error": f"SMTP error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }

    # ========================================================================
    # SMS Methods
    # ========================================================================

    async def send_sms(
        self,
        phone_number: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send an SMS message.

        Args:
            phone_number: Recipient phone number in E.164 format (e.g., +15551234567)
            message: Message content (max 160 chars for single SMS)

        Returns:
            Dictionary with 'success', 'message_id', 'provider', and optionally 'error'
        """
        if not settings.NOTIFICATION_ENABLED:
            logger.debug("Notifications are disabled")
            return {
                "success": False,
                "message_id": None,
                "provider": None,
                "error": "Notifications disabled"
            }

        if not settings.sms_enabled:
            logger.warning("SMS is not configured")
            return {
                "success": False,
                "message_id": None,
                "provider": None,
                "error": "SMS not configured"
            }

        # Validate phone number format (basic check)
        if not phone_number.startswith("+"):
            logger.warning(f"Phone number should be in E.164 format: {phone_number}")

        result = await self.sms_provider.send_sms(phone_number, message)
        result["provider"] = settings.SMS_PROVIDER

        return result

    # ========================================================================
    # Template Rendering
    # ========================================================================

    def render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        """
        Render an HTML template with the given context.

        Args:
            template_name: Name of the template file
            context: Dictionary of template variables

        Returns:
            Rendered HTML string
        """
        try:
            template = self.template_env.get_template(template_name)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Error rendering template {template_name}: {str(e)}")
            raise

    # ========================================================================
    # User Preference Methods
    # ========================================================================

    async def get_user_preferences(self, user_id: str) -> Optional[UserNotificationPreference]:
        """Get notification preferences for a user."""
        result = await self.db.execute(
            select(UserNotificationPreference).where(
                UserNotificationPreference.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_user_preferences(
        self,
        user_id: str
    ) -> UserNotificationPreference:
        """Get or create notification preferences for a user."""
        prefs = await self.get_user_preferences(user_id)

        if not prefs:
            prefs = UserNotificationPreference(user_id=user_id)
            self.db.add(prefs)
            await self.db.commit()
            await self.db.refresh(prefs)

        return prefs

    async def get_tenant_settings(self, tenant_id: str) -> Optional[TenantNotificationSettings]:
        """Get notification settings for a tenant."""
        result = await self.db.execute(
            select(TenantNotificationSettings).where(
                TenantNotificationSettings.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()

    async def should_send_notification(
        self,
        user: User,
        event_type: NotificationEventType,
        channel: NotificationChannel
    ) -> bool:
        """
        Check if a notification should be sent based on user and tenant preferences.

        Args:
            user: The user to check
            event_type: The type of notification event
            channel: The notification channel (email/sms)

        Returns:
            True if notification should be sent, False otherwise
        """
        # Check global settings
        if not settings.NOTIFICATION_ENABLED:
            return False

        # Check tenant settings
        tenant_settings = await self.get_tenant_settings(user.tenant_id)
        if tenant_settings:
            if channel == NotificationChannel.EMAIL and not tenant_settings.email_notifications_enabled:
                return False
            if channel == NotificationChannel.SMS and not tenant_settings.sms_notifications_enabled:
                return False

        # Check user preferences
        prefs = await self.get_user_preferences(user.id)
        if not prefs:
            return True  # Default to sending if no preferences set

        # Check global channel toggle
        if channel == NotificationChannel.EMAIL and not prefs.email_enabled:
            return False
        if channel == NotificationChannel.SMS and not prefs.sms_enabled:
            return False

        # Check event-specific preference
        pref_mapping = {
            (NotificationEventType.TICKET_CREATED, NotificationChannel.EMAIL): prefs.email_on_ticket_created,
            (NotificationEventType.TICKET_CREATED, NotificationChannel.SMS): prefs.sms_on_ticket_created,
            (NotificationEventType.TICKET_ASSIGNED, NotificationChannel.EMAIL): prefs.email_on_ticket_assigned,
            (NotificationEventType.TICKET_ASSIGNED, NotificationChannel.SMS): prefs.sms_on_ticket_assigned,
            (NotificationEventType.TICKET_STATUS_CHANGED, NotificationChannel.EMAIL): prefs.email_on_ticket_status_changed,
            (NotificationEventType.TICKET_STATUS_CHANGED, NotificationChannel.SMS): prefs.sms_on_ticket_status_changed,
            (NotificationEventType.TICKET_COMMENT_ADDED, NotificationChannel.EMAIL): prefs.email_on_ticket_comment,
            (NotificationEventType.TICKET_COMMENT_ADDED, NotificationChannel.SMS): prefs.sms_on_ticket_comment,
            (NotificationEventType.SLA_BREACH, NotificationChannel.EMAIL): prefs.email_on_sla_breach,
            (NotificationEventType.SLA_BREACH, NotificationChannel.SMS): prefs.sms_on_sla_breach,
            (NotificationEventType.SLA_WARNING, NotificationChannel.EMAIL): prefs.email_on_sla_warning,
            (NotificationEventType.SLA_WARNING, NotificationChannel.SMS): prefs.sms_on_sla_warning,
            (NotificationEventType.WORKLOG_ADDED, NotificationChannel.EMAIL): prefs.email_on_worklog_added,
            (NotificationEventType.WORKLOG_ADDED, NotificationChannel.SMS): prefs.sms_on_worklog_added,
            (NotificationEventType.ASSIGNMENT_DUE, NotificationChannel.EMAIL): prefs.email_on_assignment_due,
            (NotificationEventType.ASSIGNMENT_DUE, NotificationChannel.SMS): prefs.sms_on_assignment_due,
        }

        return pref_mapping.get((event_type, channel), True)

    # ========================================================================
    # Notification Logging
    # ========================================================================

    async def log_notification(
        self,
        tenant_id: str,
        event_type: NotificationEventType,
        channel: NotificationChannel,
        status: NotificationStatus,
        recipient_email: Optional[str] = None,
        recipient_phone: Optional[str] = None,
        user_id: Optional[str] = None,
        subject: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        related_ticket_id: Optional[str] = None,
        provider: Optional[str] = None,
        provider_message_id: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> NotificationLog:
        """Log a notification for auditing."""
        log = NotificationLog(
            tenant_id=tenant_id,
            user_id=user_id,
            recipient_email=recipient_email,
            recipient_phone=recipient_phone,
            event_type=event_type,
            channel=channel,
            status=status,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            related_ticket_id=related_ticket_id,
            provider=provider,
            provider_message_id=provider_message_id,
            error_message=error_message,
            sent_at=datetime.utcnow() if status == NotificationStatus.SENT else None,
            failed_at=datetime.utcnow() if status == NotificationStatus.FAILED else None
        )

        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        return log

    # ========================================================================
    # Event-Based Notification Methods
    # ========================================================================

    async def _get_ticket_with_relations(self, ticket_id: str) -> Optional[Ticket]:
        """Get ticket with all related data for notifications."""
        result = await self.db.execute(
            select(Ticket)
            .options(
                selectinload(Ticket.site),
                selectinload(Ticket.charger),
                selectinload(Ticket.tenant),
                selectinload(Ticket.created_by_user),
                selectinload(Ticket.assignments).selectinload(Assignment.assignee_user)
            )
            .where(Ticket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    def _build_ticket_url(self, ticket_id: str) -> str:
        """Build the URL to view a ticket."""
        return f"{settings.FRONTEND_BASE_URL}/tickets/{ticket_id}"

    async def notify_ticket_created(
        self,
        ticket: Ticket,
        notify_users: Optional[List[User]] = None
    ) -> List[Dict[str, Any]]:
        """
        Send notifications when a new ticket is created.

        Args:
            ticket: The newly created ticket
            notify_users: Optional list of users to notify (defaults to tenant admins)

        Returns:
            List of notification results
        """
        results = []

        # Load ticket relations if not already loaded
        if not hasattr(ticket, 'site') or ticket.site is None:
            ticket = await self._get_ticket_with_relations(ticket.id)
            if not ticket:
                logger.error(f"Ticket not found: {ticket.id}")
                return results

        # Build template context
        context = {
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category.value.replace("_", " ").title(),
            "priority": ticket.priority.value,
            "site_name": ticket.site.name if ticket.site else "Unknown",
            "charger_id": ticket.charger.charger_id if ticket.charger else None,
            "reporter_name": ticket.reporter_name or "Unknown",
            "reporter_email": ticket.reporter_email or "",
            "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M UTC"),
            "ticket_url": self._build_ticket_url(ticket.id),
        }

        # Render HTML template
        html_body = self.render_template("ticket_created.html", context)

        # Build plain text body
        text_body = f"""
New Ticket Created: {ticket.ticket_number}

Title: {ticket.title}
Category: {context['category']}
Priority: {ticket.priority.value.upper()}
Site: {context['site_name']}
Reporter: {context['reporter_name']}

Description:
{ticket.description or 'No description provided'}

View ticket: {context['ticket_url']}
"""

        subject = f"[CASS] New Ticket: {ticket.ticket_number} - {ticket.title}"

        # Get users to notify (tenant admins and managers by default)
        if not notify_users:
            from app.models.user import UserRole
            result = await self.db.execute(
                select(User).where(
                    and_(
                        User.tenant_id == ticket.tenant_id,
                        User.is_active == True,
                        User.role.in_([UserRole.ADMIN, UserRole.TENANT_ADMIN, UserRole.AS_MANAGER])
                    )
                )
            )
            notify_users = result.scalars().all()

        # Send notifications
        for user in notify_users:
            # Check email preference
            if user.email and await self.should_send_notification(
                user, NotificationEventType.TICKET_CREATED, NotificationChannel.EMAIL
            ):
                email_result = await self.send_email(
                    to=user.email,
                    subject=subject,
                    body=text_body,
                    html_body=html_body
                )
                results.append({
                    "user_id": user.id,
                    "channel": "email",
                    **email_result
                })

                # Log notification
                await self.log_notification(
                    tenant_id=ticket.tenant_id,
                    event_type=NotificationEventType.TICKET_CREATED,
                    channel=NotificationChannel.EMAIL,
                    status=NotificationStatus.SENT if email_result["success"] else NotificationStatus.FAILED,
                    recipient_email=user.email,
                    user_id=user.id,
                    subject=subject,
                    body_text=text_body,
                    body_html=html_body,
                    related_ticket_id=ticket.id,
                    provider="smtp",
                    provider_message_id=email_result.get("message_id"),
                    error_message=email_result.get("error")
                )

            # Check SMS preference
            if user.phone and await self.should_send_notification(
                user, NotificationEventType.TICKET_CREATED, NotificationChannel.SMS
            ):
                sms_message = f"CASS: New ticket {ticket.ticket_number} - {ticket.title[:50]}. Priority: {ticket.priority.value.upper()}"
                sms_result = await self.send_sms(user.phone, sms_message)
                results.append({
                    "user_id": user.id,
                    "channel": "sms",
                    **sms_result
                })

                await self.log_notification(
                    tenant_id=ticket.tenant_id,
                    event_type=NotificationEventType.TICKET_CREATED,
                    channel=NotificationChannel.SMS,
                    status=NotificationStatus.SENT if sms_result["success"] else NotificationStatus.FAILED,
                    recipient_phone=user.phone,
                    user_id=user.id,
                    body_text=sms_message,
                    related_ticket_id=ticket.id,
                    provider=sms_result.get("provider"),
                    provider_message_id=sms_result.get("message_id"),
                    error_message=sms_result.get("error")
                )

        return results

    async def notify_ticket_assigned(
        self,
        ticket: Ticket,
        assignee: User,
        assignment: Optional[Assignment] = None,
        assigned_by: Optional[User] = None
    ) -> List[Dict[str, Any]]:
        """
        Send notifications when a ticket is assigned to someone.

        Args:
            ticket: The ticket being assigned
            assignee: The user being assigned to the ticket
            assignment: Optional assignment record
            assigned_by: Optional user who made the assignment

        Returns:
            List of notification results
        """
        results = []

        # Load ticket relations
        if not hasattr(ticket, 'site') or ticket.site is None:
            ticket = await self._get_ticket_with_relations(ticket.id)
            if not ticket:
                return results

        context = {
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category.value.replace("_", " ").title(),
            "priority": ticket.priority.value,
            "status": ticket.current_status.value.replace("_", " ").title(),
            "site_name": ticket.site.name if ticket.site else "Unknown",
            "charger_id": ticket.charger.charger_id if ticket.charger else None,
            "assignee_name": assignee.full_name,
            "assigned_by": assigned_by.full_name if assigned_by else "System",
            "assigned_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "due_at": assignment.due_at.strftime("%Y-%m-%d %H:%M UTC") if assignment and assignment.due_at else None,
            "notes": assignment.notes if assignment else None,
            "ticket_url": self._build_ticket_url(ticket.id),
        }

        html_body = self.render_template("ticket_assigned.html", context)

        text_body = f"""
You have been assigned to ticket: {ticket.ticket_number}

Title: {ticket.title}
Priority: {ticket.priority.value.upper()}
Site: {context['site_name']}
Assigned by: {context['assigned_by']}
{'Due: ' + context['due_at'] if context['due_at'] else ''}

View ticket: {context['ticket_url']}
"""

        subject = f"[CASS] Ticket Assigned: {ticket.ticket_number} - {ticket.title}"

        # Send email to assignee
        if assignee.email and await self.should_send_notification(
            assignee, NotificationEventType.TICKET_ASSIGNED, NotificationChannel.EMAIL
        ):
            email_result = await self.send_email(
                to=assignee.email,
                subject=subject,
                body=text_body,
                html_body=html_body
            )
            results.append({
                "user_id": assignee.id,
                "channel": "email",
                **email_result
            })

            await self.log_notification(
                tenant_id=ticket.tenant_id,
                event_type=NotificationEventType.TICKET_ASSIGNED,
                channel=NotificationChannel.EMAIL,
                status=NotificationStatus.SENT if email_result["success"] else NotificationStatus.FAILED,
                recipient_email=assignee.email,
                user_id=assignee.id,
                subject=subject,
                related_ticket_id=ticket.id,
                error_message=email_result.get("error")
            )

        # Send SMS to assignee
        if assignee.phone and await self.should_send_notification(
            assignee, NotificationEventType.TICKET_ASSIGNED, NotificationChannel.SMS
        ):
            sms_message = f"CASS: Ticket {ticket.ticket_number} assigned to you. {ticket.title[:30]}. Priority: {ticket.priority.value.upper()}"
            sms_result = await self.send_sms(assignee.phone, sms_message)
            results.append({
                "user_id": assignee.id,
                "channel": "sms",
                **sms_result
            })

            await self.log_notification(
                tenant_id=ticket.tenant_id,
                event_type=NotificationEventType.TICKET_ASSIGNED,
                channel=NotificationChannel.SMS,
                status=NotificationStatus.SENT if sms_result["success"] else NotificationStatus.FAILED,
                recipient_phone=assignee.phone,
                user_id=assignee.id,
                body_text=sms_message,
                related_ticket_id=ticket.id,
                provider=sms_result.get("provider"),
                error_message=sms_result.get("error")
            )

        return results

    async def notify_ticket_status_changed(
        self,
        ticket: Ticket,
        old_status: str,
        new_status: str,
        changed_by: Optional[User] = None,
        reason: Optional[str] = None,
        notify_users: Optional[List[User]] = None
    ) -> List[Dict[str, Any]]:
        """
        Send notifications when a ticket's status changes.

        Args:
            ticket: The ticket with changed status
            old_status: Previous status value
            new_status: New status value
            changed_by: User who made the change
            reason: Optional reason for the change
            notify_users: Optional list of users to notify

        Returns:
            List of notification results
        """
        results = []

        if not hasattr(ticket, 'site') or ticket.site is None:
            ticket = await self._get_ticket_with_relations(ticket.id)
            if not ticket:
                return results

        # Get current assignee
        assignee_name = None
        if ticket.assignments:
            latest_assignment = ticket.assignments[-1]
            if latest_assignment.assignee_user:
                assignee_name = latest_assignment.assignee_user.full_name

        context = {
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "category": ticket.category.value.replace("_", " ").title(),
            "priority": ticket.priority.value,
            "old_status": old_status,
            "new_status": new_status,
            "site_name": ticket.site.name if ticket.site else "Unknown",
            "assignee_name": assignee_name,
            "changed_by": changed_by.full_name if changed_by else "System",
            "changed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "reason": reason,
            "resolution_summary": ticket.resolution_summary if new_status in ["resolved", "closed"] else None,
            "ticket_url": self._build_ticket_url(ticket.id),
        }

        html_body = self.render_template("ticket_status_changed.html", context)

        text_body = f"""
Ticket Status Updated: {ticket.ticket_number}

Status changed from {old_status.replace('_', ' ').title()} to {new_status.replace('_', ' ').title()}

Title: {ticket.title}
Changed by: {context['changed_by']}
{f'Reason: {reason}' if reason else ''}

View ticket: {context['ticket_url']}
"""

        subject = f"[CASS] Status Updated: {ticket.ticket_number} - {new_status.replace('_', ' ').title()}"

        # Determine who to notify
        if not notify_users:
            users_to_notify = set()

            # Notify ticket creator
            if ticket.created_by_user:
                users_to_notify.add(ticket.created_by_user)

            # Notify assignees
            for assignment in ticket.assignments:
                if assignment.assignee_user:
                    users_to_notify.add(assignment.assignee_user)

            notify_users = list(users_to_notify)

        for user in notify_users:
            if user.email and await self.should_send_notification(
                user, NotificationEventType.TICKET_STATUS_CHANGED, NotificationChannel.EMAIL
            ):
                email_result = await self.send_email(
                    to=user.email,
                    subject=subject,
                    body=text_body,
                    html_body=html_body
                )
                results.append({
                    "user_id": user.id,
                    "channel": "email",
                    **email_result
                })

            if user.phone and await self.should_send_notification(
                user, NotificationEventType.TICKET_STATUS_CHANGED, NotificationChannel.SMS
            ):
                sms_message = f"CASS: Ticket {ticket.ticket_number} status: {old_status} -> {new_status}"
                sms_result = await self.send_sms(user.phone, sms_message)
                results.append({
                    "user_id": user.id,
                    "channel": "sms",
                    **sms_result
                })

        return results

    async def notify_sla_breach(
        self,
        ticket: Ticket,
        breach_type: str = "resolution",  # "response" or "resolution"
        response_breached: bool = False,
        resolution_breached: bool = False,
        response_target_minutes: Optional[int] = None,
        resolution_target_minutes: Optional[int] = None,
        actual_response_minutes: Optional[float] = None,
        elapsed_minutes: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Send notifications when an SLA is breached.

        Args:
            ticket: The ticket with breached SLA
            breach_type: Type of breach ("response" or "resolution")
            response_breached: Whether response SLA is breached
            resolution_breached: Whether resolution SLA is breached
            response_target_minutes: Target response time in minutes
            resolution_target_minutes: Target resolution time in minutes
            actual_response_minutes: Actual response time if applicable
            elapsed_minutes: Time elapsed since ticket creation

        Returns:
            List of notification results
        """
        results = []

        if not hasattr(ticket, 'site') or ticket.site is None:
            ticket = await self._get_ticket_with_relations(ticket.id)
            if not ticket:
                return results

        # Get current assignee
        assignee_name = None
        if ticket.assignments:
            latest_assignment = ticket.assignments[-1]
            if latest_assignment.assignee_user:
                assignee_name = latest_assignment.assignee_user.full_name

        context = {
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "category": ticket.category.value.replace("_", " ").title(),
            "priority": ticket.priority.value,
            "status": ticket.current_status.value.replace("_", " ").title(),
            "site_name": ticket.site.name if ticket.site else "Unknown",
            "assignee_name": assignee_name,
            "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M UTC"),
            "breached_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "response_breached": response_breached,
            "resolution_breached": resolution_breached,
            "response_target_minutes": response_target_minutes,
            "resolution_target_minutes": resolution_target_minutes,
            "actual_response_minutes": round(actual_response_minutes) if actual_response_minutes else None,
            "elapsed_minutes": round(elapsed_minutes) if elapsed_minutes else None,
            "ticket_url": self._build_ticket_url(ticket.id),
        }

        html_body = self.render_template("sla_breach.html", context)

        breach_text = []
        if response_breached:
            breach_text.append("Response SLA")
        if resolution_breached:
            breach_text.append("Resolution SLA")

        text_body = f"""
SLA BREACH ALERT: {ticket.ticket_number}

{' and '.join(breach_text)} has been breached!

Title: {ticket.title}
Priority: {ticket.priority.value.upper()}
Site: {context['site_name']}
Current Status: {context['status']}
Assigned To: {assignee_name or 'Unassigned'}

IMMEDIATE ACTION REQUIRED

View ticket: {context['ticket_url']}
"""

        subject = f"[CASS] SLA BREACH: {ticket.ticket_number} - {ticket.title}"

        # Notify assignees and managers
        from app.models.user import UserRole
        result = await self.db.execute(
            select(User).where(
                and_(
                    User.tenant_id == ticket.tenant_id,
                    User.is_active == True,
                    User.role.in_([UserRole.ADMIN, UserRole.TENANT_ADMIN, UserRole.AS_MANAGER])
                )
            )
        )
        managers = result.scalars().all()

        # Also notify assignees
        notify_users = set(managers)
        for assignment in ticket.assignments:
            if assignment.assignee_user:
                notify_users.add(assignment.assignee_user)

        for user in notify_users:
            if user.email and await self.should_send_notification(
                user, NotificationEventType.SLA_BREACH, NotificationChannel.EMAIL
            ):
                email_result = await self.send_email(
                    to=user.email,
                    subject=subject,
                    body=text_body,
                    html_body=html_body
                )
                results.append({
                    "user_id": user.id,
                    "channel": "email",
                    **email_result
                })

                await self.log_notification(
                    tenant_id=ticket.tenant_id,
                    event_type=NotificationEventType.SLA_BREACH,
                    channel=NotificationChannel.EMAIL,
                    status=NotificationStatus.SENT if email_result["success"] else NotificationStatus.FAILED,
                    recipient_email=user.email,
                    user_id=user.id,
                    subject=subject,
                    related_ticket_id=ticket.id,
                    error_message=email_result.get("error")
                )

            if user.phone and await self.should_send_notification(
                user, NotificationEventType.SLA_BREACH, NotificationChannel.SMS
            ):
                sms_message = f"CASS SLA BREACH: Ticket {ticket.ticket_number} - {' & '.join(breach_text)} breached. URGENT action required."
                sms_result = await self.send_sms(user.phone, sms_message)
                results.append({
                    "user_id": user.id,
                    "channel": "sms",
                    **sms_result
                })

                await self.log_notification(
                    tenant_id=ticket.tenant_id,
                    event_type=NotificationEventType.SLA_BREACH,
                    channel=NotificationChannel.SMS,
                    status=NotificationStatus.SENT if sms_result["success"] else NotificationStatus.FAILED,
                    recipient_phone=user.phone,
                    user_id=user.id,
                    body_text=sms_message,
                    related_ticket_id=ticket.id,
                    provider=sms_result.get("provider"),
                    error_message=sms_result.get("error")
                )

        return results

    async def notify_worklog_added(
        self,
        ticket: Ticket,
        worklog: Worklog,
        notify_users: Optional[List[User]] = None
    ) -> List[Dict[str, Any]]:
        """
        Send notifications when a worklog is added to a ticket.

        Args:
            ticket: The ticket with the new worklog
            worklog: The new worklog entry
            notify_users: Optional list of users to notify

        Returns:
            List of notification results
        """
        results = []

        if not hasattr(ticket, 'site') or ticket.site is None:
            ticket = await self._get_ticket_with_relations(ticket.id)
            if not ticket:
                return results

        # Get worklog author
        author_result = await self.db.execute(
            select(User).where(User.id == worklog.author_id)
        )
        author = author_result.scalar_one_or_none()

        context = {
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "priority": ticket.priority.value,
            "status": ticket.current_status.value.replace("_", " ").title(),
            "site_name": ticket.site.name if ticket.site else "Unknown",
            "author_name": author.full_name if author else "Unknown",
            "worklog_body": worklog.body,
            "work_type": worklog.work_type.value,
            "time_spent_minutes": worklog.time_spent_minutes,
            "created_at": worklog.created_at.strftime("%Y-%m-%d %H:%M UTC"),
            "ticket_url": self._build_ticket_url(ticket.id),
        }

        html_body = self.render_template("worklog_added.html", context)

        text_body = f"""
New Worklog Entry: {ticket.ticket_number}

Author: {context['author_name']}
Work Type: {worklog.work_type.value.replace('_', ' ').title()}
{f'Time Spent: {worklog.time_spent_minutes} minutes' if worklog.time_spent_minutes else ''}

Entry:
{worklog.body}

View ticket: {context['ticket_url']}
"""

        subject = f"[CASS] Worklog Added: {ticket.ticket_number}"

        # Determine who to notify
        if not notify_users:
            users_to_notify = set()

            # Notify ticket creator (if different from worklog author)
            if ticket.created_by_user and ticket.created_by != worklog.author_id:
                users_to_notify.add(ticket.created_by_user)

            # Notify other assignees (if different from worklog author)
            for assignment in ticket.assignments:
                if assignment.assignee_user and assignment.assignee_user_id != worklog.author_id:
                    users_to_notify.add(assignment.assignee_user)

            notify_users = list(users_to_notify)

        for user in notify_users:
            if user.email and await self.should_send_notification(
                user, NotificationEventType.WORKLOG_ADDED, NotificationChannel.EMAIL
            ):
                email_result = await self.send_email(
                    to=user.email,
                    subject=subject,
                    body=text_body,
                    html_body=html_body
                )
                results.append({
                    "user_id": user.id,
                    "channel": "email",
                    **email_result
                })

            if user.phone and await self.should_send_notification(
                user, NotificationEventType.WORKLOG_ADDED, NotificationChannel.SMS
            ):
                sms_message = f"CASS: New worklog on {ticket.ticket_number} by {context['author_name'][:15]}"
                sms_result = await self.send_sms(user.phone, sms_message)
                results.append({
                    "user_id": user.id,
                    "channel": "sms",
                    **sms_result
                })

        return results

    # ========================================================================
    # Test Notification Method
    # ========================================================================

    async def send_test_notification(
        self,
        channel: NotificationChannel,
        recipient: str,
        subject: Optional[str] = None,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a test notification to verify configuration.

        Args:
            channel: Notification channel (email or sms)
            recipient: Email address or phone number
            subject: Optional custom subject (email only)
            message: Optional custom message

        Returns:
            Result dictionary with success status and details
        """
        default_subject = "Test Notification from CASS"
        default_message = "This is a test notification to verify your notification settings are working correctly."

        if channel == NotificationChannel.EMAIL:
            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #0066cc;">Test Notification</h2>
                <p>{message or default_message}</p>
                <hr style="border: 1px solid #eee;">
                <p style="color: #666; font-size: 12px;">
                    This is a test notification from CASS (Charging Asset Service System).<br>
                    Sent at: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}
                </p>
            </div>
            """

            result = await self.send_email(
                to=recipient,
                subject=subject or default_subject,
                body=message or default_message,
                html_body=html_body
            )

            return {
                "success": result["success"],
                "channel": channel.value,
                "recipient": recipient,
                "message": "Test email sent successfully" if result["success"] else "Failed to send test email",
                "provider_message_id": result.get("message_id"),
                "error": result.get("error")
            }

        elif channel == NotificationChannel.SMS:
            sms_message = message or f"CASS Test: {default_message}"

            result = await self.send_sms(recipient, sms_message)

            return {
                "success": result["success"],
                "channel": channel.value,
                "recipient": recipient,
                "message": "Test SMS sent successfully" if result["success"] else "Failed to send test SMS",
                "provider_message_id": result.get("message_id"),
                "error": result.get("error")
            }

        else:
            return {
                "success": False,
                "channel": channel.value,
                "recipient": recipient,
                "message": f"Unsupported channel: {channel.value}",
                "error": "Unsupported notification channel"
            }
