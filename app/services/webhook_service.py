"""Webhook service for processing CSMS webhooks."""
import hashlib
import hmac
import logging
from datetime import datetime
from typing import Optional, Tuple
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.asset import Charger
from app.models.csms import CsmsEventRef, FirmwareJobRef, FirmwareJobStatus
from app.models.ticket import Ticket, TicketChannel, TicketCategory, TicketPriority, TicketStatus
from app.models.user import User, UserRole
from app.schemas.webhook import (
    CSMSWebhookPayload,
    ChargerEventPayload,
    ChargerEventSeverity,
    FirmwareUpdatePayload,
    FirmwareUpdateStatus,
    WebhookEventType,
    WebhookResponse,
)


# System user email pattern for each tenant
SYSTEM_USER_EMAIL_TEMPLATE = "system@cass.internal"


logger = logging.getLogger(__name__)


# Mapping of CSMS fault codes to ticket categories
FAULT_CATEGORY_MAP = {
    "ConnectorLockFailure": TicketCategory.CONNECTOR,
    "EVCommunicationError": TicketCategory.NETWORK,
    "GroundFailure": TicketCategory.HARDWARE,
    "HighTemperature": TicketCategory.HARDWARE,
    "InternalError": TicketCategory.SOFTWARE,
    "LocalListConflict": TicketCategory.SOFTWARE,
    "NoError": TicketCategory.OTHER,
    "OtherError": TicketCategory.OTHER,
    "OverCurrentFailure": TicketCategory.POWER,
    "OverVoltage": TicketCategory.POWER,
    "PowerMeterFailure": TicketCategory.POWER,
    "PowerSwitchFailure": TicketCategory.POWER,
    "ReaderFailure": TicketCategory.HARDWARE,
    "ResetFailure": TicketCategory.SOFTWARE,
    "UnderVoltage": TicketCategory.POWER,
    "WeakSignal": TicketCategory.NETWORK,
}

# Mapping of severity to ticket priority
SEVERITY_PRIORITY_MAP = {
    ChargerEventSeverity.CRITICAL: TicketPriority.CRITICAL,
    ChargerEventSeverity.ERROR: TicketPriority.HIGH,
    ChargerEventSeverity.WARNING: TicketPriority.MEDIUM,
    ChargerEventSeverity.INFO: TicketPriority.LOW,
}


class WebhookService:
    """Service for processing CSMS webhooks."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._system_user_cache: dict[str, str] = {}  # tenant_id -> user_id

    async def get_or_create_system_user(self, tenant_id: str) -> str:
        """
        Get or create a system user for auto-generated tickets.

        Each tenant has a dedicated system user for webhook-created tickets.
        The user is created on first use and cached for subsequent calls.

        Args:
            tenant_id: The tenant ID

        Returns:
            The system user ID
        """
        # Check cache first
        if tenant_id in self._system_user_cache:
            return self._system_user_cache[tenant_id]

        # Look for existing system user
        system_email = f"system+{tenant_id[:8]}@cass.internal"
        result = await self.db.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.email == system_email
            )
        )
        system_user = result.scalar_one_or_none()

        if system_user:
            self._system_user_cache[tenant_id] = system_user.id
            return system_user.id

        # Create system user for this tenant
        system_user = User(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=system_email,
            hashed_password="!SYSTEM_USER_NO_LOGIN!",  # Cannot be used for login
            role=UserRole.ADMIN,  # System user has admin role for internal operations
            full_name="CASS System",
            is_active=True,
            is_verified=True,
        )

        self.db.add(system_user)
        await self.db.flush()

        self._system_user_cache[tenant_id] = system_user.id
        logger.info(f"Created system user for tenant {tenant_id}: {system_user.id}")

        return system_user.id

    @staticmethod
    def verify_signature(payload: bytes, signature: str, timestamp: Optional[str] = None) -> bool:
        """
        Verify the webhook signature using HMAC-SHA256.

        Args:
            payload: Raw request body bytes
            signature: Signature header value from CSMS
            timestamp: Optional timestamp header for replay attack prevention

        Returns:
            True if signature is valid, False otherwise
        """
        if not settings.CSMS_WEBHOOK_SECRET:
            logger.warning("CSMS_WEBHOOK_SECRET is not configured, skipping signature verification")
            return True

        try:
            # Build the message to sign
            if timestamp:
                message = f"{timestamp}.{payload.decode('utf-8')}"
            else:
                message = payload.decode("utf-8")

            # Calculate expected signature
            expected_signature = hmac.new(
                settings.CSMS_WEBHOOK_SECRET.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            # Compare signatures (timing-safe comparison)
            # Handle both raw hex and prefixed formats (e.g., "sha256=...")
            actual_signature = signature.replace("sha256=", "").strip()

            return hmac.compare_digest(expected_signature, actual_signature)

        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False

    async def get_charger_by_csms_id(self, csms_charger_id: str) -> Optional[Charger]:
        """Get charger by CSMS charger ID."""
        result = await self.db.execute(
            select(Charger).where(Charger.csms_charger_id == csms_charger_id)
        )
        return result.scalar_one_or_none()

    async def process_generic_webhook(self, payload: CSMSWebhookPayload) -> WebhookResponse:
        """
        Process a generic CSMS webhook.

        Args:
            payload: The webhook payload

        Returns:
            WebhookResponse with processing result
        """
        # Find the charger
        charger = await self.get_charger_by_csms_id(payload.csms_charger_id)
        if not charger:
            logger.warning(f"Charger not found for CSMS ID: {payload.csms_charger_id}")
            return WebhookResponse(
                success=False,
                message=f"Charger not found for CSMS ID: {payload.csms_charger_id}",
                event_id=payload.event_id
            )

        # Store the event (without ticket association for now)
        event_ref = CsmsEventRef(
            id=str(uuid.uuid4()),
            ticket_id=None,  # Will be linked if ticket is created
            charger_id=charger.id,
            csms_event_id=payload.event_id,
            event_type=payload.event_type.value,
            event_data=payload.data,
            occurred_at=payload.timestamp
        )

        # Note: Cannot add without ticket_id due to NOT NULL constraint
        # For generic events, we just log them
        logger.info(
            f"Received webhook event: type={payload.event_type}, "
            f"charger={payload.csms_charger_id}, event_id={payload.event_id}"
        )

        return WebhookResponse(
            success=True,
            message="Event received and logged",
            event_id=payload.event_id
        )

    async def process_charger_event(self, payload: ChargerEventPayload) -> WebhookResponse:
        """
        Process a charger event webhook.

        Creates a ticket for critical faults and stores the event reference.

        Args:
            payload: The charger event payload

        Returns:
            WebhookResponse with processing result
        """
        # Find the charger
        charger = await self.get_charger_by_csms_id(payload.csms_charger_id)
        if not charger:
            logger.warning(f"Charger not found for CSMS ID: {payload.csms_charger_id}")
            return WebhookResponse(
                success=False,
                message=f"Charger not found for CSMS ID: {payload.csms_charger_id}",
                event_id=payload.event_id
            )

        ticket_id: Optional[str] = None
        internal_ref_id: Optional[str] = None

        # Check if this is a critical or error event that requires a ticket
        should_create_ticket = (
            payload.severity in [ChargerEventSeverity.CRITICAL, ChargerEventSeverity.ERROR]
            or payload.event_type == WebhookEventType.FAULT
        )

        if should_create_ticket:
            # Create a ticket for this fault
            ticket, event_ref = await self._create_fault_ticket(charger, payload)
            ticket_id = ticket.id
            internal_ref_id = event_ref.id

            logger.info(
                f"Created ticket {ticket.ticket_number} for fault on charger {charger.serial_number}"
            )
        else:
            # Update charger status for non-critical events
            await self._update_charger_status(charger, payload)
            logger.info(
                f"Updated charger status: {charger.serial_number} -> {payload.status}"
            )

        await self.db.commit()

        return WebhookResponse(
            success=True,
            message="Charger event processed successfully",
            event_id=payload.event_id,
            internal_ref_id=internal_ref_id,
            ticket_id=ticket_id
        )

    async def _create_fault_ticket(
        self,
        charger: Charger,
        payload: ChargerEventPayload
    ) -> Tuple[Ticket, CsmsEventRef]:
        """Create a ticket for a charger fault."""
        # Get or create system user for this tenant
        system_user_id = await self.get_or_create_system_user(charger.tenant_id)

        # Generate ticket number
        ticket_number = f"AUTO-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

        # Determine category from error code
        category = FAULT_CATEGORY_MAP.get(payload.error_code, TicketCategory.OTHER)

        # Determine priority from severity
        priority = SEVERITY_PRIORITY_MAP.get(payload.severity, TicketPriority.MEDIUM)

        # Build ticket title and description
        title = f"[AUTO] {payload.event_type.value}: {charger.name}"
        if payload.error_code:
            title = f"[AUTO] {payload.error_code}: {charger.name}"

        description = self._build_fault_description(charger, payload)

        # Create the ticket
        ticket = Ticket(
            id=str(uuid.uuid4()),
            tenant_id=charger.tenant_id,
            site_id=charger.site_id,
            charger_id=charger.id,
            ticket_number=ticket_number,
            title=title,
            description=description,
            channel=TicketChannel.AUTO,
            category=category,
            priority=priority,
            current_status=TicketStatus.NEW,
            created_by=system_user_id,  # System user for auto-created tickets
            opened_at=payload.timestamp,
        )

        self.db.add(ticket)
        await self.db.flush()  # Get the ticket ID

        # Create the CSMS event reference
        event_ref = CsmsEventRef(
            id=str(uuid.uuid4()),
            ticket_id=ticket.id,
            charger_id=charger.id,
            csms_event_id=payload.event_id,
            event_type=payload.event_type.value,
            event_data={
                "severity": payload.severity.value,
                "status": payload.status,
                "error_code": payload.error_code,
                "vendor_error_code": payload.vendor_error_code,
                "info": payload.info,
                "fault_type": payload.fault_type,
                "fault_description": payload.fault_description,
                "connector_id": payload.connector_id,
                **payload.data
            },
            occurred_at=payload.timestamp
        )

        self.db.add(event_ref)

        return ticket, event_ref

    def _build_fault_description(self, charger: Charger, payload: ChargerEventPayload) -> str:
        """Build a detailed description for a fault ticket."""
        lines = [
            "## Auto-generated Fault Ticket",
            "",
            f"**Charger:** {charger.name} ({charger.serial_number})",
            f"**CSMS Charger ID:** {payload.csms_charger_id}",
            f"**Event Type:** {payload.event_type.value}",
            f"**Severity:** {payload.severity.value.upper()}",
            f"**Occurred At:** {payload.timestamp.isoformat()}",
        ]

        if payload.connector_id:
            lines.append(f"**Connector ID:** {payload.connector_id}")

        if payload.error_code:
            lines.append(f"**Error Code:** {payload.error_code}")

        if payload.vendor_error_code:
            lines.append(f"**Vendor Error Code:** {payload.vendor_error_code}")

        if payload.fault_type:
            lines.append(f"**Fault Type:** {payload.fault_type}")

        if payload.fault_description:
            lines.extend(["", "### Fault Description", payload.fault_description])

        if payload.info:
            lines.extend(["", "### Additional Information", payload.info])

        lines.extend([
            "",
            "---",
            f"*This ticket was automatically created from CSMS event {payload.event_id}*"
        ])

        return "\n".join(lines)

    async def _update_charger_status(self, charger: Charger, payload: ChargerEventPayload) -> None:
        """Update charger status from event."""
        if payload.status:
            charger.current_status = payload.status
            charger.last_status_update = payload.timestamp

    async def process_firmware_update(self, payload: FirmwareUpdatePayload) -> WebhookResponse:
        """
        Process a firmware update status webhook.

        Updates the firmware job reference status and may update the ticket.

        Args:
            payload: The firmware update payload

        Returns:
            WebhookResponse with processing result
        """
        # Find the charger
        charger = await self.get_charger_by_csms_id(payload.csms_charger_id)
        if not charger:
            logger.warning(f"Charger not found for CSMS ID: {payload.csms_charger_id}")
            return WebhookResponse(
                success=False,
                message=f"Charger not found for CSMS ID: {payload.csms_charger_id}",
                event_id=payload.event_id
            )

        # Find the firmware job reference
        result = await self.db.execute(
            select(FirmwareJobRef).where(
                FirmwareJobRef.csms_job_id == payload.csms_job_id,
                FirmwareJobRef.charger_id == charger.id
            )
        )
        firmware_job = result.scalar_one_or_none()

        if not firmware_job:
            logger.warning(
                f"Firmware job not found: csms_job_id={payload.csms_job_id}, "
                f"charger_id={charger.id}"
            )
            return WebhookResponse(
                success=False,
                message=f"Firmware job not found: {payload.csms_job_id}",
                event_id=payload.event_id
            )

        # Map CSMS status to internal status
        status_map = {
            FirmwareUpdateStatus.SCHEDULED: FirmwareJobStatus.SCHEDULED,
            FirmwareUpdateStatus.DOWNLOADING: FirmwareJobStatus.DOWNLOADING,
            FirmwareUpdateStatus.DOWNLOADED: FirmwareJobStatus.DOWNLOADED,
            FirmwareUpdateStatus.INSTALLING: FirmwareJobStatus.INSTALLING,
            FirmwareUpdateStatus.INSTALLED: FirmwareJobStatus.INSTALLED,
            FirmwareUpdateStatus.FAILED: FirmwareJobStatus.FAILED,
            FirmwareUpdateStatus.CANCELLED: FirmwareJobStatus.CANCELLED,
        }

        # Update firmware job status
        firmware_job.last_status = status_map.get(payload.status, FirmwareJobStatus.REQUESTED)
        firmware_job.status_message = payload.status_message
        firmware_job.last_checked_at = datetime.utcnow()

        # Update version info if available
        if payload.current_version:
            firmware_job.current_version = payload.current_version
        if payload.target_version:
            firmware_job.target_version = payload.target_version
        if payload.applied_version:
            firmware_job.applied_version = payload.applied_version

        # Set completion timestamp for terminal states
        if payload.status in [
            FirmwareUpdateStatus.INSTALLED,
            FirmwareUpdateStatus.FAILED,
            FirmwareUpdateStatus.CANCELLED
        ]:
            firmware_job.completed_at = payload.timestamp

            # Update charger firmware version if successfully installed
            if payload.status == FirmwareUpdateStatus.INSTALLED and payload.applied_version:
                charger.firmware_version = payload.applied_version
                logger.info(
                    f"Updated charger {charger.serial_number} firmware to {payload.applied_version}"
                )

        await self.db.commit()

        logger.info(
            f"Updated firmware job {payload.csms_job_id} status to {payload.status.value}"
        )

        return WebhookResponse(
            success=True,
            message=f"Firmware update status updated: {payload.status.value}",
            event_id=payload.event_id,
            internal_ref_id=firmware_job.id,
            ticket_id=firmware_job.ticket_id
        )


async def get_webhook_service(db: AsyncSession) -> WebhookService:
    """Dependency for getting webhook service."""
    return WebhookService(db)
