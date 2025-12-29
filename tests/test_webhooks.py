"""
Tests for Webhook Processing and Signature Verification

Tests cover:
- Webhook signature verification (HMAC-SHA256)
- CSMS generic webhook processing
- Charger event webhook handling
- Firmware update status webhooks
- Batch webhook processing
- Auto-ticket creation for critical faults
- Error handling for invalid payloads
"""
import pytest
import hashlib
import hmac
import json
from datetime import datetime
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from unittest.mock import patch

from app.core.config import settings
from app.models.ticket import Ticket, TicketStatus, TicketChannel, TicketCategory, TicketPriority
from app.models.asset import Charger
from app.models.tenant import Tenant
from app.models.csms import FirmwareJobRef, FirmwareJobStatus
from app.services.webhook_service import WebhookService
from app.schemas.webhook import (
    WebhookEventType,
    ChargerEventSeverity,
    FirmwareUpdateStatus
)
from tests.conftest import ChargerFactory, TenantFactory, SiteFactory


# -----------------------------------------------------------------------------
# Signature Verification Tests
# -----------------------------------------------------------------------------

class TestSignatureVerification:
    """Tests for webhook signature verification."""

    def test_verify_signature_valid(self):
        """Test verification of valid signature."""
        payload = b'{"event_id": "test123"}'
        secret = "test_secret_key"
        timestamp = "1234567890"

        # Generate signature
        message = f"{timestamp}.{payload.decode('utf-8')}"
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        with patch.object(settings, 'CSMS_WEBHOOK_SECRET', secret):
            result = WebhookService.verify_signature(
                payload, expected_sig, timestamp
            )

        assert result is True

    def test_verify_signature_invalid(self):
        """Test verification of invalid signature."""
        payload = b'{"event_id": "test123"}'
        secret = "test_secret_key"
        timestamp = "1234567890"
        invalid_sig = "invalid_signature_here"

        with patch.object(settings, 'CSMS_WEBHOOK_SECRET', secret):
            result = WebhookService.verify_signature(
                payload, invalid_sig, timestamp
            )

        assert result is False

    def test_verify_signature_without_timestamp(self):
        """Test verification without timestamp header."""
        payload = b'{"event_id": "test123"}'
        secret = "test_secret_key"

        # Generate signature without timestamp
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        with patch.object(settings, 'CSMS_WEBHOOK_SECRET', secret):
            result = WebhookService.verify_signature(
                payload, expected_sig, None
            )

        assert result is True

    def test_verify_signature_with_sha256_prefix(self):
        """Test verification with sha256= prefix in signature."""
        payload = b'{"event_id": "test123"}'
        secret = "test_secret_key"

        expected_sig = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        # Add sha256= prefix
        prefixed_sig = f"sha256={expected_sig}"

        with patch.object(settings, 'CSMS_WEBHOOK_SECRET', secret):
            result = WebhookService.verify_signature(
                payload, prefixed_sig, None
            )

        assert result is True

    def test_verify_signature_empty_secret(self):
        """Test that empty secret skips verification."""
        payload = b'{"event_id": "test123"}'

        with patch.object(settings, 'CSMS_WEBHOOK_SECRET', ''):
            result = WebhookService.verify_signature(
                payload, "any_signature", None
            )

        # Should return True when secret is not configured
        assert result is True


# -----------------------------------------------------------------------------
# Generic Webhook Tests
# -----------------------------------------------------------------------------

class TestGenericWebhook:
    """Tests for generic CSMS webhook processing."""

    @pytest.mark.asyncio
    async def test_receive_generic_webhook_charger_not_found(
        self,
        client: AsyncClient
    ):
        """Test webhook for non-existent charger."""
        payload = {
            "event_id": "evt_123456",
            "event_type": "StatusNotification",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": "NON_EXISTENT_CHARGER",
            "data": {"status": "Available"}
        }

        response = await client.post(
            "/api/v1/webhooks/csms",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_receive_generic_webhook_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test successful generic webhook processing."""
        # Create a charger
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-TEST-001"
        )

        payload = {
            "event_id": "evt_789",
            "event_type": "StatusNotification",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": charger.csms_charger_id,
            "data": {"status": "Available", "connector_id": 1}
        }

        response = await client.post(
            "/api/v1/webhooks/csms",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["event_id"] == "evt_789"

    @pytest.mark.asyncio
    async def test_webhook_invalid_payload(
        self,
        client: AsyncClient
    ):
        """Test webhook with invalid payload structure."""
        payload = {
            "event_id": "evt_123",
            # Missing required fields
        }

        response = await client.post(
            "/api/v1/webhooks/csms",
            json=payload
        )

        assert response.status_code == 422


# -----------------------------------------------------------------------------
# Charger Event Webhook Tests
# -----------------------------------------------------------------------------

class TestChargerEventWebhook:
    """Tests for charger event webhook processing."""

    @pytest.mark.asyncio
    async def test_critical_fault_creates_ticket(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test that critical fault event creates a ticket."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-FAULT-001"
        )

        payload = {
            "event_id": "evt_fault_001",
            "event_type": "Fault",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": charger.csms_charger_id,
            "severity": "critical",
            "connector_id": 1,
            "status": "Faulted",
            "error_code": "GroundFailure",
            "fault_type": "Hardware",
            "fault_description": "Ground fault protection triggered"
        }

        response = await client.post(
            "/api/v1/webhooks/csms/events",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["ticket_id"] is not None

        # Verify ticket was created
        result = await db_session.execute(
            select(Ticket).where(Ticket.id == data["ticket_id"])
        )
        ticket = result.scalar_one_or_none()

        assert ticket is not None
        assert ticket.channel == TicketChannel.AUTO
        assert ticket.priority == TicketPriority.CRITICAL
        assert ticket.current_status == TicketStatus.NEW
        assert "GroundFailure" in ticket.title

    @pytest.mark.asyncio
    async def test_error_event_creates_ticket(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test that error severity event creates a ticket."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-ERROR-001"
        )

        payload = {
            "event_id": "evt_error_001",
            "event_type": "Fault",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": charger.csms_charger_id,
            "severity": "error",
            "error_code": "OverVoltage",
            "fault_description": "Voltage exceeds safe limits"
        }

        response = await client.post(
            "/api/v1/webhooks/csms/events",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["ticket_id"] is not None

        # Verify ticket priority
        result = await db_session.execute(
            select(Ticket).where(Ticket.id == data["ticket_id"])
        )
        ticket = result.scalar_one_or_none()
        assert ticket.priority == TicketPriority.HIGH

    @pytest.mark.asyncio
    async def test_warning_event_no_ticket(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test that warning event does not create a ticket."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-WARN-001"
        )

        payload = {
            "event_id": "evt_warn_001",
            "event_type": "StatusNotification",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": charger.csms_charger_id,
            "severity": "warning",
            "status": "Available",
            "info": "Minor connectivity fluctuation detected"
        }

        response = await client.post(
            "/api/v1/webhooks/csms/events",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["ticket_id"] is None

    @pytest.mark.asyncio
    async def test_fault_category_mapping(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test that fault codes map to correct ticket categories."""
        test_cases = [
            ("GroundFailure", TicketCategory.HARDWARE),
            ("OverVoltage", TicketCategory.POWER),
            ("WeakSignal", TicketCategory.NETWORK),
            ("ConnectorLockFailure", TicketCategory.CONNECTOR),
            ("InternalError", TicketCategory.SOFTWARE),
        ]

        for error_code, expected_category in test_cases:
            charger = await ChargerFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                csms_charger_id=f"CSMS-CAT-{error_code}"
            )

            payload = {
                "event_id": f"evt_cat_{error_code}",
                "event_type": "Fault",
                "timestamp": datetime.utcnow().isoformat(),
                "csms_charger_id": charger.csms_charger_id,
                "severity": "critical",
                "error_code": error_code
            }

            response = await client.post(
                "/api/v1/webhooks/csms/events",
                json=payload
            )

            assert response.status_code == 200
            data = response.json()

            # Verify category
            result = await db_session.execute(
                select(Ticket).where(Ticket.id == data["ticket_id"])
            )
            ticket = result.scalar_one_or_none()
            assert ticket.category == expected_category, f"Failed for {error_code}"


# -----------------------------------------------------------------------------
# Firmware Update Webhook Tests
# -----------------------------------------------------------------------------

class TestFirmwareUpdateWebhook:
    """Tests for firmware update status webhooks."""

    @pytest.mark.asyncio
    async def test_firmware_update_charger_not_found(
        self,
        client: AsyncClient
    ):
        """Test firmware webhook for non-existent charger."""
        payload = {
            "event_id": "evt_fw_001",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": "NON_EXISTENT",
            "csms_job_id": "fwjob_001",
            "status": "installing",
            "target_version": "2.0.0"
        }

        response = await client.post(
            "/api/v1/webhooks/csms/firmware",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_firmware_job_not_found(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test firmware webhook for non-existent job."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-FW-001"
        )

        payload = {
            "event_id": "evt_fw_002",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": charger.csms_charger_id,
            "csms_job_id": "NON_EXISTENT_JOB",
            "status": "installing"
        }

        response = await client.post(
            "/api/v1/webhooks/csms/firmware",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "job not found" in data["message"].lower()


# -----------------------------------------------------------------------------
# Batch Webhook Tests
# -----------------------------------------------------------------------------

class TestBatchWebhook:
    """Tests for batch webhook processing."""

    @pytest.mark.asyncio
    async def test_batch_webhook_multiple_events(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test processing multiple events in batch."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-BATCH-001"
        )

        payload = {
            "batch_id": "batch_001",
            "events": [
                {
                    "event_id": "evt_batch_1",
                    "event_type": "StatusNotification",
                    "timestamp": datetime.utcnow().isoformat(),
                    "csms_charger_id": charger.csms_charger_id,
                    "data": {"status": "Available"}
                },
                {
                    "event_id": "evt_batch_2",
                    "event_type": "Heartbeat",
                    "timestamp": datetime.utcnow().isoformat(),
                    "csms_charger_id": charger.csms_charger_id,
                    "data": {}
                }
            ]
        }

        response = await client.post(
            "/api/v1/webhooks/csms/batch",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["batch_id"] == "batch_001"
        assert data["total_events"] == 2
        assert data["processed_events"] == 2
        assert data["failed_events"] == 0

    @pytest.mark.asyncio
    async def test_batch_webhook_partial_failure(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test batch with some failing events."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-BATCH-002"
        )

        payload = {
            "batch_id": "batch_002",
            "events": [
                {
                    "event_id": "evt_batch_ok",
                    "event_type": "StatusNotification",
                    "timestamp": datetime.utcnow().isoformat(),
                    "csms_charger_id": charger.csms_charger_id,
                    "data": {"status": "Available"}
                },
                {
                    "event_id": "evt_batch_fail",
                    "event_type": "StatusNotification",
                    "timestamp": datetime.utcnow().isoformat(),
                    "csms_charger_id": "NON_EXISTENT_CHARGER",
                    "data": {"status": "Available"}
                }
            ]
        }

        response = await client.post(
            "/api/v1/webhooks/csms/batch",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["processed_events"] == 1
        assert data["failed_events"] == 1
        assert len(data["errors"]) == 1

    @pytest.mark.asyncio
    async def test_batch_webhook_empty_events(
        self,
        client: AsyncClient
    ):
        """Test batch with empty events list."""
        payload = {
            "batch_id": "batch_empty",
            "events": []
        }

        response = await client.post(
            "/api/v1/webhooks/csms/batch",
            json=payload
        )

        # Should fail validation - events must have at least 1 item
        assert response.status_code == 422


# -----------------------------------------------------------------------------
# Webhook Health Check Tests
# -----------------------------------------------------------------------------

class TestWebhookHealthCheck:
    """Tests for webhook health check endpoint."""

    @pytest.mark.asyncio
    async def test_webhook_health_check(
        self,
        client: AsyncClient
    ):
        """Test health check endpoint returns correct structure."""
        response = await client.get("/api/v1/webhooks/csms/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "csms-webhook"
        assert "endpoints" in data
        assert "generic" in data["endpoints"]
        assert "events" in data["endpoints"]
        assert "firmware" in data["endpoints"]
        assert "batch" in data["endpoints"]


# -----------------------------------------------------------------------------
# Signature Header Tests
# -----------------------------------------------------------------------------

class TestSignatureHeaders:
    """Tests for webhook signature header handling."""

    @pytest.mark.asyncio
    async def test_webhook_without_signature_dev_mode(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test webhook without signature in development mode."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-SIG-001"
        )

        payload = {
            "event_id": "evt_nosig",
            "event_type": "StatusNotification",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": charger.csms_charger_id,
            "data": {"status": "Available"}
        }

        # No signature headers - should still work in dev
        response = await client.post(
            "/api/v1/webhooks/csms",
            json=payload
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_webhook_with_invalid_signature(
        self,
        client: AsyncClient
    ):
        """Test webhook with invalid signature header."""
        payload = {
            "event_id": "evt_badsig",
            "event_type": "StatusNotification",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": "CHARGER_001",
            "data": {}
        }

        # With invalid signature header and configured secret
        with patch.object(settings, 'CSMS_WEBHOOK_SECRET', 'secret_key'):
            response = await client.post(
                "/api/v1/webhooks/csms",
                json=payload,
                headers={
                    "X-CSMS-Signature": "invalid_signature",
                    "X-CSMS-Timestamp": "1234567890"
                }
            )

        assert response.status_code == 401
        data = response.json()
        assert "signature" in data["detail"].lower()


# -----------------------------------------------------------------------------
# Auto-Ticket Description Tests
# -----------------------------------------------------------------------------

class TestAutoTicketDescription:
    """Tests for auto-generated ticket descriptions."""

    @pytest.mark.asyncio
    async def test_ticket_description_contains_fault_info(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site
    ):
        """Test that auto-ticket description contains fault information."""
        charger = await ChargerFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            csms_charger_id="CSMS-DESC-001",
            name="Test Charger Alpha"
        )

        payload = {
            "event_id": "evt_desc_001",
            "event_type": "Fault",
            "timestamp": datetime.utcnow().isoformat(),
            "csms_charger_id": charger.csms_charger_id,
            "severity": "critical",
            "connector_id": 2,
            "error_code": "OverCurrentFailure",
            "vendor_error_code": "V-E001",
            "fault_type": "Power",
            "fault_description": "Current exceeded safe threshold on connector 2",
            "info": "Immediate shutdown required"
        }

        response = await client.post(
            "/api/v1/webhooks/csms/events",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()

        # Get ticket and check description
        result = await db_session.execute(
            select(Ticket).where(Ticket.id == data["ticket_id"])
        )
        ticket = result.scalar_one_or_none()

        description = ticket.description
        assert "Test Charger Alpha" in description
        assert "CSMS-DESC-001" in description
        assert "OverCurrentFailure" in description
        assert "Connector ID: 2" in description or "Connector ID:** 2" in description
        assert "Current exceeded safe threshold" in description
