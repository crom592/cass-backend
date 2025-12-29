"""
Tests for Ticket CRUD Operations and Status Changes

Tests cover:
- Creating tickets
- Reading tickets (list and single)
- Updating ticket details
- Changing ticket status
- Filtering tickets by various criteria
- Ticket history retrieval
- Access control for different user roles
"""
import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory, TicketChannel
from app.models.user import User
from app.models.tenant import Tenant
from app.models.asset import Site, Charger
from tests.conftest import TicketFactory, ChargerFactory


# -----------------------------------------------------------------------------
# Ticket Creation Tests
# -----------------------------------------------------------------------------

class TestTicketCreation:
    """Tests for creating new tickets."""

    @pytest.mark.asyncio
    async def test_create_ticket_success(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_site: Site
    ):
        """Test successful ticket creation with minimum required fields."""
        payload = {
            "site_id": test_site.id,
            "title": "Charger not responding",
            "category": "hardware",
            "priority": "high"
        }

        response = await client.post(
            "/api/v1/tickets",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Charger not responding"
        assert data["current_status"] == "new"
        assert data["priority"] == "high"
        assert data["category"] == "hardware"
        assert data["ticket_number"].startswith("TKT-")
        assert data["site_id"] == test_site.id
        assert data["sla_breached"] is False

    @pytest.mark.asyncio
    async def test_create_ticket_with_all_fields(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_site: Site,
        test_charger: Charger
    ):
        """Test ticket creation with all optional fields."""
        payload = {
            "site_id": test_site.id,
            "charger_id": test_charger.id,
            "title": "Ground fault detected",
            "description": "Charger shows ground fault error on connector 1",
            "channel": "phone",
            "category": "power",
            "priority": "critical",
            "reporter_name": "John Doe",
            "reporter_email": "john@example.com",
            "reporter_phone": "+1234567890"
        }

        response = await client.post(
            "/api/v1/tickets",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Ground fault detected"
        assert data["description"] == "Charger shows ground fault error on connector 1"
        assert data["channel"] == "phone"
        assert data["charger_id"] == test_charger.id
        assert data["reporter_name"] == "John Doe"
        assert data["reporter_email"] == "john@example.com"

    @pytest.mark.asyncio
    async def test_create_ticket_unauthorized(
        self,
        client: AsyncClient,
        test_site: Site
    ):
        """Test that unauthenticated requests are rejected."""
        payload = {
            "site_id": test_site.id,
            "title": "Test ticket"
        }

        response = await client.post("/api/v1/tickets", json=payload)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_ticket_missing_required_fields(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test that missing required fields return validation error."""
        payload = {
            "title": "Test ticket"
            # Missing site_id
        }

        response = await client.post(
            "/api/v1/tickets",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_ticket_engineer_role(
        self,
        client: AsyncClient,
        auth_headers_engineer: dict,
        test_site: Site
    ):
        """Test that engineers can create tickets."""
        payload = {
            "site_id": test_site.id,
            "title": "On-site inspection report",
            "category": "hardware"
        }

        response = await client.post(
            "/api/v1/tickets",
            json=payload,
            headers=auth_headers_engineer
        )

        assert response.status_code == 201


# -----------------------------------------------------------------------------
# Ticket Retrieval Tests
# -----------------------------------------------------------------------------

class TestTicketRetrieval:
    """Tests for reading tickets."""

    @pytest.mark.asyncio
    async def test_get_ticket_by_id(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test retrieving a single ticket by ID."""
        response = await client.get(
            f"/api/v1/tickets/{test_ticket.id}",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_ticket.id
        assert data["ticket_number"] == test_ticket.ticket_number

    @pytest.mark.asyncio
    async def test_get_ticket_not_found(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test that non-existent ticket returns 404."""
        response = await client.get(
            "/api/v1/tickets/non-existent-id",
            headers=auth_headers_admin
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_tickets(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test listing multiple tickets."""
        # Create multiple tickets
        for i in range(5):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                title=f"Test Ticket {i}"
            )

        response = await client.get(
            "/api/v1/tickets",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

    @pytest.mark.asyncio
    async def test_list_tickets_pagination(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test ticket list pagination."""
        # Create 10 tickets
        for i in range(10):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                title=f"Test Ticket {i}"
            )

        # Get first page
        response = await client.get(
            "/api/v1/tickets?skip=0&limit=5",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

        # Get second page
        response = await client.get(
            "/api/v1/tickets?skip=5&limit=5",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5


# -----------------------------------------------------------------------------
# Ticket Filter Tests
# -----------------------------------------------------------------------------

class TestTicketFilters:
    """Tests for filtering tickets."""

    @pytest.mark.asyncio
    async def test_filter_by_status(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test filtering tickets by status."""
        # Create tickets with different statuses
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.NEW
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.IN_PROGRESS
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.RESOLVED
        )

        response = await client.get(
            "/api/v1/tickets?status=new",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["current_status"] == "new"

    @pytest.mark.asyncio
    async def test_filter_by_priority(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test filtering tickets by priority."""
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            priority=TicketPriority.CRITICAL
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            priority=TicketPriority.LOW
        )

        response = await client.get(
            "/api/v1/tickets?priority=critical",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_filter_by_category(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test filtering tickets by category."""
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.NETWORK
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            category=TicketCategory.POWER
        )

        response = await client.get(
            "/api/v1/tickets?category=network",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["category"] == "network"

    @pytest.mark.asyncio
    async def test_filter_by_sla_breached(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test filtering tickets by SLA breach status."""
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            sla_breached=True
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            sla_breached=False
        )

        response = await client.get(
            "/api/v1/tickets?sla_breached=true",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["sla_breached"] is True

    @pytest.mark.asyncio
    async def test_filter_by_site_id(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test filtering tickets by site ID."""
        # Create another site
        from tests.conftest import SiteFactory
        other_site = await SiteFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            name="Other Site"
        )

        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=other_site.id,
            created_by=admin_user.id
        )

        response = await client.get(
            f"/api/v1/tickets?site_id={test_site.id}",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["site_id"] == test_site.id


# -----------------------------------------------------------------------------
# Ticket Update Tests
# -----------------------------------------------------------------------------

class TestTicketUpdate:
    """Tests for updating ticket details."""

    @pytest.mark.asyncio
    async def test_update_ticket_title(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test updating ticket title."""
        response = await client.patch(
            f"/api/v1/tickets/{test_ticket.id}",
            json={"title": "Updated Title"},
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_ticket_priority(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test updating ticket priority."""
        response = await client.patch(
            f"/api/v1/tickets/{test_ticket.id}",
            json={"priority": "critical"},
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_update_ticket_multiple_fields(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test updating multiple ticket fields at once."""
        response = await client.patch(
            f"/api/v1/tickets/{test_ticket.id}",
            json={
                "title": "New Title",
                "description": "New description",
                "category": "software",
                "reporter_name": "Jane Doe"
            },
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New Title"
        assert data["description"] == "New description"
        assert data["category"] == "software"
        assert data["reporter_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_update_ticket_not_found(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test updating non-existent ticket returns 404."""
        response = await client.patch(
            "/api/v1/tickets/non-existent-id",
            json={"title": "Updated"},
            headers=auth_headers_admin
        )

        assert response.status_code == 404


# -----------------------------------------------------------------------------
# Ticket Status Change Tests
# -----------------------------------------------------------------------------

class TestTicketStatusChange:
    """Tests for changing ticket status."""

    @pytest.mark.asyncio
    async def test_change_status_to_assigned(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test changing ticket status from NEW to ASSIGNED."""
        response = await client.post(
            f"/api/v1/tickets/{test_ticket.id}/status",
            json={
                "to_status": "assigned",
                "reason": "Assigned to field engineer"
            },
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["current_status"] == "assigned"

    @pytest.mark.asyncio
    async def test_change_status_to_in_progress(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test changing ticket status to IN_PROGRESS."""
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.ASSIGNED
        )

        response = await client.post(
            f"/api/v1/tickets/{ticket.id}/status",
            json={
                "to_status": "in_progress",
                "reason": "Started working on the issue"
            },
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["current_status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_change_status_to_resolved(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test resolving a ticket sets resolved_at timestamp."""
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.IN_PROGRESS
        )

        response = await client.post(
            f"/api/v1/tickets/{ticket.id}/status",
            json={
                "to_status": "resolved",
                "reason": "Issue fixed by replacing connector"
            },
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["current_status"] == "resolved"
        assert data["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_change_status_to_closed(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test closing a ticket sets closed_at timestamp."""
        ticket = await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.RESOLVED
        )

        response = await client.post(
            f"/api/v1/tickets/{ticket.id}/status",
            json={
                "to_status": "closed",
                "reason": "Verified by customer"
            },
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["current_status"] == "closed"
        assert data["closed_at"] is not None

    @pytest.mark.asyncio
    async def test_change_status_with_no_reason(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test status change without reason (reason is optional)."""
        response = await client.post(
            f"/api/v1/tickets/{test_ticket.id}/status",
            json={"to_status": "assigned"},
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["current_status"] == "assigned"


# -----------------------------------------------------------------------------
# Ticket History Tests
# -----------------------------------------------------------------------------

class TestTicketHistory:
    """Tests for ticket status history."""

    @pytest.mark.asyncio
    async def test_get_ticket_history(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test retrieving ticket status history."""
        # Change status a few times
        await client.post(
            f"/api/v1/tickets/{test_ticket.id}/status",
            json={"to_status": "assigned", "reason": "Assigned to engineer"},
            headers=auth_headers_admin
        )
        await client.post(
            f"/api/v1/tickets/{test_ticket.id}/status",
            json={"to_status": "in_progress", "reason": "Work started"},
            headers=auth_headers_admin
        )

        response = await client.get(
            f"/api/v1/tickets/{test_ticket.id}/history",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        # Should have 3 entries: initial creation + 2 status changes
        assert len(data) >= 2

    @pytest.mark.asyncio
    async def test_ticket_history_order(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        test_ticket: Ticket
    ):
        """Test that ticket history is ordered by date descending."""
        await client.post(
            f"/api/v1/tickets/{test_ticket.id}/status",
            json={"to_status": "assigned"},
            headers=auth_headers_admin
        )
        await client.post(
            f"/api/v1/tickets/{test_ticket.id}/status",
            json={"to_status": "in_progress"},
            headers=auth_headers_admin
        )

        response = await client.get(
            f"/api/v1/tickets/{test_ticket.id}/history",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        # Most recent should be first (in_progress)
        assert data[0]["to_status"] == "in_progress"


# -----------------------------------------------------------------------------
# Access Control Tests
# -----------------------------------------------------------------------------

class TestTicketAccessControl:
    """Tests for ticket access control."""

    @pytest.mark.asyncio
    async def test_viewer_can_read_tickets(
        self,
        client: AsyncClient,
        auth_headers_viewer: dict,
        test_ticket: Ticket
    ):
        """Test that viewers can read tickets."""
        response = await client.get(
            f"/api/v1/tickets/{test_ticket.id}",
            headers=auth_headers_viewer
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_viewer_can_list_tickets(
        self,
        client: AsyncClient,
        auth_headers_viewer: dict,
        test_ticket: Ticket
    ):
        """Test that viewers can list tickets."""
        response = await client.get(
            "/api/v1/tickets",
            headers=auth_headers_viewer
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_tenant_isolation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers_admin: dict,
        admin_user: User
    ):
        """Test that users can only see tickets from their tenant."""
        # Create another tenant with its own data
        from tests.conftest import TenantFactory, SiteFactory, UserFactory

        other_tenant = await TenantFactory.create(db_session, name="Other Tenant")
        other_site = await SiteFactory.create(db_session, tenant_id=other_tenant.id)
        other_user = await UserFactory.create(
            db_session,
            tenant_id=other_tenant.id,
            email="other@test.com"
        )

        # Create ticket in other tenant
        other_ticket = await TicketFactory.create(
            db_session,
            tenant_id=other_tenant.id,
            site_id=other_site.id,
            created_by=other_user.id
        )

        # Admin should not see the other tenant's ticket
        response = await client.get(
            f"/api/v1/tickets/{other_ticket.id}",
            headers=auth_headers_admin
        )

        assert response.status_code == 404
