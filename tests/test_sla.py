"""
Tests for SLA Calculation and Breach Detection

Tests cover:
- SLA policy CRUD operations
- SLA calculation for tickets
- Response time breach detection
- Resolution time breach detection
- SLA measurement creation and updates
- Ticket SLA status retrieval
- SLA statistics and batch recalculation
"""
import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from app.models.sla import SlaPolicy, SlaMeasurement, SlaStatus
from app.models.user import User
from app.models.tenant import Tenant
from app.models.asset import Site
from app.services.sla_service import SlaService
from tests.conftest import (
    TicketFactory,
    SlaPolicyFactory,
    SlaMeasurementFactory,
    WorklogFactory
)


# -----------------------------------------------------------------------------
# SLA Policy CRUD Tests
# -----------------------------------------------------------------------------

class TestSlaPolicyCreation:
    """Tests for creating SLA policies."""

    @pytest.mark.asyncio
    async def test_create_sla_policy(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test creating a new SLA policy."""
        payload = {
            "category": "hardware",
            "priority": "critical",
            "response_time_minutes": 30,
            "resolution_time_minutes": 240
        }

        response = await client.post(
            "/api/v1/sla/policies",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 201
        data = response.json()
        assert data["category"] == "hardware"
        assert data["priority"] == "critical"
        assert data["response_time_minutes"] == 30
        assert data["resolution_time_minutes"] == 240
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_duplicate_policy_conflict(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_sla_policy: SlaPolicy
    ):
        """Test that creating duplicate policy returns 409 conflict."""
        payload = {
            "category": test_sla_policy.category,
            "priority": test_sla_policy.priority,
            "response_time_minutes": 60,
            "resolution_time_minutes": 480
        }

        response = await client.post(
            "/api/v1/sla/policies",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_create_policy_invalid_times(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test that invalid time values are rejected."""
        payload = {
            "category": "software",
            "priority": "high",
            "response_time_minutes": 0,  # Invalid - must be > 0
            "resolution_time_minutes": 480
        }

        response = await client.post(
            "/api/v1/sla/policies",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 422


class TestSlaPolicyRetrieval:
    """Tests for retrieving SLA policies."""

    @pytest.mark.asyncio
    async def test_list_sla_policies(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant
    ):
        """Test listing all SLA policies."""
        # Create multiple policies
        await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="critical"
        )
        await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="software",
            priority="high"
        )

        response = await client.get(
            "/api/v1/sla/policies",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_list_active_policies_only(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant
    ):
        """Test filtering to show only active policies."""
        # Create active and inactive policies
        active = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="medium"
        )
        inactive = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="software",
            priority="low"
        )
        inactive.is_active = False
        await db_session.commit()

        response = await client.get(
            "/api/v1/sla/policies?active_only=true",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        # Only active policies should be returned
        for policy in data["policies"]:
            assert policy["is_active"] is True

    @pytest.mark.asyncio
    async def test_get_single_policy(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_sla_policy: SlaPolicy
    ):
        """Test retrieving a single policy by ID."""
        response = await client.get(
            f"/api/v1/sla/policies/{test_sla_policy.id}",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_sla_policy.id

    @pytest.mark.asyncio
    async def test_get_policy_not_found(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test that non-existent policy returns 404."""
        response = await client.get(
            "/api/v1/sla/policies/non-existent-id",
            headers=auth_headers_admin
        )

        assert response.status_code == 404


class TestSlaPolicyUpdate:
    """Tests for updating SLA policies."""

    @pytest.mark.asyncio
    async def test_update_policy_times(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_sla_policy: SlaPolicy
    ):
        """Test updating policy response and resolution times."""
        response = await client.patch(
            f"/api/v1/sla/policies/{test_sla_policy.id}",
            json={
                "response_time_minutes": 45,
                "resolution_time_minutes": 360
            },
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_time_minutes"] == 45
        assert data["resolution_time_minutes"] == 360

    @pytest.mark.asyncio
    async def test_deactivate_policy(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_sla_policy: SlaPolicy
    ):
        """Test deactivating a policy via DELETE."""
        response = await client.delete(
            f"/api/v1/sla/policies/{test_sla_policy.id}",
            headers=auth_headers_admin
        )

        assert response.status_code == 204


# -----------------------------------------------------------------------------
# SLA Calculation Tests
# -----------------------------------------------------------------------------

class TestSlaCalculation:
    """Tests for SLA calculation logic."""

    @pytest.mark.asyncio
    async def test_calculate_sla_within_target(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA calculation for ticket within target time."""
        # Create policy
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="medium",
            response_time_minutes=60,
            resolution_time_minutes=480
        )

        # Create ticket opened 30 minutes ago (within response target)
        opened_at = datetime.utcnow() - timedelta(minutes=30)
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.HARDWARE,
            priority=TicketPriority.MEDIUM,
            opened_at=opened_at
        )

        sla_service = SlaService(db_session)
        result = await sla_service.calculate_sla_for_ticket(ticket.id)

        assert result["policy_id"] == policy.id
        assert result["response_breached"] is False
        assert result["resolution_breached"] is False
        assert result["overall_status"] == SlaStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_calculate_sla_response_breached(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA calculation when response time is breached."""
        # Create policy with 30 minute response time
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="critical",
            response_time_minutes=30,
            resolution_time_minutes=240
        )

        # Create ticket opened 60 minutes ago (past response target)
        opened_at = datetime.utcnow() - timedelta(minutes=60)
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.HARDWARE,
            priority=TicketPriority.CRITICAL,
            opened_at=opened_at
        )

        sla_service = SlaService(db_session)
        result = await sla_service.calculate_sla_for_ticket(ticket.id)

        assert result["response_breached"] is True
        assert result["overall_status"] == SlaStatus.BREACHED

    @pytest.mark.asyncio
    async def test_calculate_sla_resolution_breached(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA calculation when resolution time is breached."""
        # Create policy with 4 hour resolution time
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="software",
            priority="high",
            response_time_minutes=60,
            resolution_time_minutes=240  # 4 hours
        )

        # Create ticket opened 5 hours ago
        opened_at = datetime.utcnow() - timedelta(hours=5)
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.SOFTWARE,
            priority=TicketPriority.HIGH,
            opened_at=opened_at
        )

        # Create a worklog to mark first response (within target)
        await WorklogFactory.create(
            db_session,
            ticket_id=ticket.id,
            author_id=admin_user.id,
            is_internal=False,
            body="Initial response"
        )

        sla_service = SlaService(db_session)
        result = await sla_service.calculate_sla_for_ticket(ticket.id)

        assert result["resolution_breached"] is True
        assert result["overall_status"] == SlaStatus.BREACHED

    @pytest.mark.asyncio
    async def test_calculate_sla_no_policy(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA calculation when no policy exists."""
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.OTHER,  # No policy for this
            priority=TicketPriority.LOW
        )

        sla_service = SlaService(db_session)
        result = await sla_service.calculate_sla_for_ticket(ticket.id)

        assert result["policy_id"] is None
        assert result["response_breached"] is False
        assert result["resolution_breached"] is False

    @pytest.mark.asyncio
    async def test_calculate_sla_resolved_within_target(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA calculation for resolved ticket within target."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="network",
            priority="medium",
            response_time_minutes=60,
            resolution_time_minutes=480
        )

        # Create resolved ticket
        opened_at = datetime.utcnow() - timedelta(hours=4)
        resolved_at = datetime.utcnow() - timedelta(hours=1)  # Resolved after 3 hours

        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.NETWORK,
            priority=TicketPriority.MEDIUM,
            status=TicketStatus.RESOLVED,
            opened_at=opened_at
        )
        ticket.resolved_at = resolved_at
        await db_session.commit()

        # Add worklog for first response
        await WorklogFactory.create(
            db_session,
            ticket_id=ticket.id,
            author_id=admin_user.id,
            is_internal=False
        )

        sla_service = SlaService(db_session)
        result = await sla_service.calculate_sla_for_ticket(ticket.id)

        assert result["resolution_breached"] is False
        assert result["overall_status"] == SlaStatus.MET


# -----------------------------------------------------------------------------
# SLA Breach Detection Tests
# -----------------------------------------------------------------------------

class TestSlaBreachDetection:
    """Tests for SLA breach detection."""

    @pytest.mark.asyncio
    async def test_check_breach_not_breached(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test breach check for ticket not breached."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="low",
            response_time_minutes=120,
            resolution_time_minutes=960
        )

        # Recent ticket
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.HARDWARE,
            priority=TicketPriority.LOW,
            opened_at=datetime.utcnow() - timedelta(minutes=30)
        )

        sla_service = SlaService(db_session)
        result = await sla_service.check_sla_breach(ticket.id)

        assert result["is_breached"] is False
        assert result["breach_type"] is None
        assert result["time_to_response_breach_minutes"] is not None
        assert result["time_to_response_breach_minutes"] > 0

    @pytest.mark.asyncio
    async def test_check_breach_response_only(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test breach check when only response is breached."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="power",
            priority="high",
            response_time_minutes=30,
            resolution_time_minutes=480
        )

        # Ticket opened 1 hour ago (response breached, resolution not)
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.POWER,
            priority=TicketPriority.HIGH,
            opened_at=datetime.utcnow() - timedelta(hours=1)
        )

        sla_service = SlaService(db_session)
        result = await sla_service.check_sla_breach(ticket.id)

        assert result["is_breached"] is True
        assert result["response_breached"] is True
        assert result["resolution_breached"] is False
        assert result["breach_type"] == "response"

    @pytest.mark.asyncio
    async def test_check_breach_both(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test breach check when both response and resolution are breached."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="connector",
            priority="critical",
            response_time_minutes=15,
            resolution_time_minutes=60
        )

        # Ticket opened 2 hours ago (both breached)
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.CONNECTOR,
            priority=TicketPriority.CRITICAL,
            opened_at=datetime.utcnow() - timedelta(hours=2)
        )

        sla_service = SlaService(db_session)
        result = await sla_service.check_sla_breach(ticket.id)

        assert result["is_breached"] is True
        assert result["response_breached"] is True
        assert result["resolution_breached"] is True
        assert result["breach_type"] == "both"


# -----------------------------------------------------------------------------
# SLA Measurement Tests
# -----------------------------------------------------------------------------

class TestSlaMeasurements:
    """Tests for SLA measurement creation and updates."""

    @pytest.mark.asyncio
    async def test_initialize_sla_for_new_ticket(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA measurement initialization for new ticket."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="medium",
            response_time_minutes=60,
            resolution_time_minutes=480
        )

        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.HARDWARE,
            priority=TicketPriority.MEDIUM
        )

        sla_service = SlaService(db_session)
        measurement = await sla_service.initialize_sla_for_new_ticket(ticket)

        assert measurement is not None
        assert measurement.ticket_id == ticket.id
        assert measurement.policy_id == policy.id
        assert measurement.status == SlaStatus.ACTIVE
        assert measurement.response_breached is False
        assert measurement.resolution_breached is False

    @pytest.mark.asyncio
    async def test_update_sla_measurements(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test updating SLA measurements."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="firmware",
            priority="low",
            response_time_minutes=30,
            resolution_time_minutes=240
        )

        # Create ticket that has breached response
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.FIRMWARE,
            priority=TicketPriority.LOW,
            opened_at=datetime.utcnow() - timedelta(hours=1)
        )

        sla_service = SlaService(db_session)
        measurement = await sla_service.update_sla_measurements(ticket.id)

        assert measurement is not None
        assert measurement.response_breached is True
        assert measurement.breached_at is not None

        # Verify ticket flag is updated
        await db_session.refresh(ticket)
        assert ticket.sla_breached is True


# -----------------------------------------------------------------------------
# SLA API Endpoint Tests
# -----------------------------------------------------------------------------

class TestSlaApiEndpoints:
    """Tests for SLA API endpoints."""

    @pytest.mark.asyncio
    async def test_get_ticket_sla_status(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test getting SLA status for a ticket."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="high",
            response_time_minutes=60,
            resolution_time_minutes=480
        )

        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.HARDWARE,
            priority=TicketPriority.HIGH
        )

        # Initialize SLA measurement
        sla_service = SlaService(db_session)
        await sla_service.initialize_sla_for_new_ticket(ticket)

        response = await client.get(
            f"/api/v1/sla/tickets/{ticket.id}",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ticket_id"] == ticket.id
        assert data["policy"] is not None
        assert data["measurement"] is not None

    @pytest.mark.asyncio
    async def test_check_ticket_breach_status(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test checking breach status endpoint."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="network",
            priority="medium",
            response_time_minutes=60,
            resolution_time_minutes=480
        )

        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.NETWORK,
            priority=TicketPriority.MEDIUM
        )

        response = await client.get(
            f"/api/v1/sla/tickets/{ticket.id}/breach",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert "is_breached" in data
        assert "response_breached" in data
        assert "resolution_breached" in data

    @pytest.mark.asyncio
    async def test_recalculate_ticket_sla(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test manual SLA recalculation endpoint."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="power",
            priority="critical",
            response_time_minutes=15,
            resolution_time_minutes=120
        )

        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.POWER,
            priority=TicketPriority.CRITICAL,
            opened_at=datetime.utcnow() - timedelta(hours=1)
        )

        response = await client.post(
            f"/api/v1/sla/tickets/{ticket.id}/recalculate",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ticket_id"] == ticket.id
        # Should be breached after 1 hour with 15 min target
        assert data["sla_breached"] is True

    @pytest.mark.asyncio
    async def test_get_sla_statistics(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA statistics endpoint."""
        # Create some tickets with SLA data
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="hardware",
            priority="high",
            response_time_minutes=60,
            resolution_time_minutes=480
        )

        for i in range(3):
            ticket = await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                category=TicketCategory.HARDWARE,
                priority=TicketPriority.HIGH,
                sla_breached=(i == 0)  # First ticket breached
            )
            await SlaMeasurementFactory.create(
                db_session,
                ticket_id=ticket.id,
                policy_id=policy.id,
                response_breached=(i == 0)
            )

        response = await client.get(
            "/api/v1/sla/statistics?days=30",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_tickets" in data
        assert "breach_rate_percentage" in data

    @pytest.mark.asyncio
    async def test_list_sla_measurements(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test listing SLA measurements."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="software",
            priority="medium"
        )

        for i in range(3):
            ticket = await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                category=TicketCategory.SOFTWARE,
                priority=TicketPriority.MEDIUM
            )
            await SlaMeasurementFactory.create(
                db_session,
                ticket_id=ticket.id,
                policy_id=policy.id
            )

        response = await client.get(
            "/api/v1/sla/measurements",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3

    @pytest.mark.asyncio
    async def test_filter_measurements_by_breach_status(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test filtering measurements by breach status."""
        policy = await SlaPolicyFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            category="other",
            priority="low"
        )

        # Create breached and non-breached measurements
        for breached in [True, False]:
            ticket = await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                category=TicketCategory.OTHER,
                priority=TicketPriority.LOW
            )
            await SlaMeasurementFactory.create(
                db_session,
                ticket_id=ticket.id,
                policy_id=policy.id,
                response_breached=breached
            )

        response = await client.get(
            "/api/v1/sla/measurements?response_breached=true",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        for measurement in data:
            assert measurement["response_breached"] is True
