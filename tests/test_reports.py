"""
Tests for Report Generation and Snapshot Management

Tests cover:
- Real-time report summary generation
- CSV export functionality
- Daily, weekly, and monthly snapshot generation
- Snapshot retrieval and listing
- Snapshot deletion with permissions
- Report metrics calculation
- SLA compliance rate calculation
- Top sites by ticket count
"""
import pytest
from datetime import datetime, date, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from app.models.report import ReportSnapshot, PeriodType
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.asset import Site
from app.services.report_service import ReportService
from tests.conftest import (
    TicketFactory,
    SiteFactory,
    ReportSnapshotFactory,
    UserFactory
)


# -----------------------------------------------------------------------------
# Report Summary Tests
# -----------------------------------------------------------------------------

class TestReportSummary:
    """Tests for real-time report summary generation."""

    @pytest.mark.asyncio
    async def test_get_report_summary(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test getting report summary with tickets."""
        # Create tickets with various statuses and priorities
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.NEW,
            priority=TicketPriority.CRITICAL
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.CLOSED,
            priority=TicketPriority.HIGH,
            sla_breached=True
        )
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id,
            status=TicketStatus.IN_PROGRESS,
            priority=TicketPriority.MEDIUM
        )

        response = await client.get(
            "/api/v1/reports/summary",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickets"] == 3
        assert "by_status" in data
        assert "by_priority" in data
        assert "by_category" in data
        assert data["sla_breached"] == 1

    @pytest.mark.asyncio
    async def test_report_summary_empty(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test report summary with no tickets."""
        response = await client.get(
            "/api/v1/reports/summary",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickets"] == 0
        assert data["sla_compliance_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_report_summary_with_date_filter(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test report summary with date range filter."""
        # Create ticket for today
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id
        )

        today = date.today()
        response = await client.get(
            f"/api/v1/reports/summary?from_date={today.isoformat()}&to_date={today.isoformat()}",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickets"] >= 1

    @pytest.mark.asyncio
    async def test_report_summary_sla_compliance_calculation(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test SLA compliance rate calculation."""
        # Create 4 tickets, 1 breached (25% breach rate = 75% compliance)
        for i in range(4):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                sla_breached=(i == 0)  # First one breached
            )

        response = await client.get(
            "/api/v1/reports/summary",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickets"] == 4
        assert data["sla_breached"] == 1
        assert data["sla_compliance_rate"] == 0.75


# -----------------------------------------------------------------------------
# CSV Export Tests
# -----------------------------------------------------------------------------

class TestCsvExport:
    """Tests for CSV export functionality."""

    @pytest.mark.asyncio
    async def test_export_tickets_csv(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test exporting tickets to CSV."""
        # Create test tickets
        for i in range(3):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                title=f"Test Ticket {i}"
            )

        response = await client.get(
            "/api/v1/reports/export",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]

        # Verify CSV content
        content = response.text
        lines = content.strip().split('\n')
        assert len(lines) >= 4  # Header + 3 tickets

        # Check header
        header = lines[0]
        assert "Ticket Number" in header
        assert "Title" in header
        assert "Status" in header
        assert "Priority" in header

    @pytest.mark.asyncio
    async def test_export_csv_with_date_filter(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test CSV export with date filter."""
        await TicketFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            site_id=test_site.id,
            created_by=admin_user.id
        )

        today = date.today()
        response = await client.get(
            f"/api/v1/reports/export?from_date={today.isoformat()}",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_export_csv_empty(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test CSV export with no tickets."""
        response = await client.get(
            "/api/v1/reports/export",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        content = response.text
        lines = content.strip().split('\n')
        # Should have header only
        assert len(lines) == 1


# -----------------------------------------------------------------------------
# Snapshot Generation Tests
# -----------------------------------------------------------------------------

class TestSnapshotGeneration:
    """Tests for report snapshot generation."""

    @pytest.mark.asyncio
    async def test_generate_daily_snapshot(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test generating a daily snapshot."""
        # Create tickets for today
        for i in range(5):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                priority=TicketPriority.HIGH if i < 2 else TicketPriority.LOW
            )

        service = ReportService(db_session)
        snapshot = await service.generate_daily_snapshot(
            tenant_id=test_tenant.id,
            target_date=date.today()
        )

        assert snapshot is not None
        assert snapshot.period_type == PeriodType.DAY
        assert snapshot.metrics["total_created"] == 5
        assert "by_priority" in snapshot.metrics
        assert "by_status" in snapshot.metrics

    @pytest.mark.asyncio
    async def test_generate_weekly_snapshot(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test generating a weekly snapshot."""
        # Create tickets
        for i in range(10):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id
            )

        service = ReportService(db_session)

        # Get this week's Monday
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        snapshot = await service.generate_weekly_snapshot(
            tenant_id=test_tenant.id,
            week_start=monday
        )

        assert snapshot is not None
        assert snapshot.period_type == PeriodType.WEEK
        # Period should be Monday to Sunday
        assert snapshot.period_start.weekday() == 0  # Monday
        assert snapshot.period_end.weekday() == 6  # Sunday

    @pytest.mark.asyncio
    async def test_generate_monthly_snapshot(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test generating a monthly snapshot."""
        for i in range(15):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id
            )

        service = ReportService(db_session)
        today = date.today()

        snapshot = await service.generate_monthly_snapshot(
            tenant_id=test_tenant.id,
            year=today.year,
            month=today.month
        )

        assert snapshot is not None
        assert snapshot.period_type == PeriodType.MONTH
        assert snapshot.period_start.day == 1
        assert snapshot.period_start.month == today.month

    @pytest.mark.asyncio
    async def test_snapshot_updates_existing(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test that regenerating snapshot updates existing one."""
        service = ReportService(db_session)
        today = date.today()

        # Generate initial snapshot
        snapshot1 = await service.generate_daily_snapshot(
            tenant_id=test_tenant.id,
            target_date=today
        )
        original_id = snapshot1.id

        # Create more tickets
        for i in range(3):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id
            )

        # Regenerate snapshot
        snapshot2 = await service.generate_daily_snapshot(
            tenant_id=test_tenant.id,
            target_date=today
        )

        # Should update existing, not create new
        assert snapshot2.id == original_id
        assert snapshot2.metrics["total_created"] == 3


# -----------------------------------------------------------------------------
# Snapshot Retrieval Tests
# -----------------------------------------------------------------------------

class TestSnapshotRetrieval:
    """Tests for snapshot retrieval."""

    @pytest.mark.asyncio
    async def test_list_snapshots(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant
    ):
        """Test listing snapshots."""
        # Create test snapshots
        for i in range(5):
            await ReportSnapshotFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                period_type=PeriodType.DAY
            )

        response = await client.get(
            "/api/v1/reports/snapshots",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 5
        assert len(data["items"]) >= 5

    @pytest.mark.asyncio
    async def test_list_snapshots_filter_by_period_type(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant
    ):
        """Test filtering snapshots by period type."""
        await ReportSnapshotFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            period_type=PeriodType.DAY
        )
        await ReportSnapshotFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            period_type=PeriodType.WEEK
        )
        await ReportSnapshotFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            period_type=PeriodType.MONTH
        )

        response = await client.get(
            "/api/v1/reports/snapshots?period_type=week",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["period_type"] == "week"

    @pytest.mark.asyncio
    async def test_get_snapshot_by_id(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant
    ):
        """Test getting a specific snapshot by ID."""
        snapshot = await ReportSnapshotFactory.create(
            db_session,
            tenant_id=test_tenant.id
        )

        response = await client.get(
            f"/api/v1/reports/snapshots/{snapshot.id}",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == snapshot.id
        assert "parsed_metrics" in data

    @pytest.mark.asyncio
    async def test_get_snapshot_not_found(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test getting non-existent snapshot returns 404."""
        response = await client.get(
            "/api/v1/reports/snapshots/non-existent-id",
            headers=auth_headers_admin
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_snapshots_pagination(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant
    ):
        """Test snapshot list pagination."""
        for i in range(15):
            await ReportSnapshotFactory.create(
                db_session,
                tenant_id=test_tenant.id
            )

        # First page
        response = await client.get(
            "/api/v1/reports/snapshots?skip=0&limit=5",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5
        assert data["skip"] == 0
        assert data["limit"] == 5


# -----------------------------------------------------------------------------
# Manual Snapshot Generation API Tests
# -----------------------------------------------------------------------------

class TestManualSnapshotGeneration:
    """Tests for manual snapshot generation API."""

    @pytest.mark.asyncio
    async def test_generate_snapshot_admin_only(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        auth_headers_viewer: dict
    ):
        """Test that only admin can generate snapshots."""
        payload = {"period_type": "day"}

        # Admin should succeed
        response = await client.post(
            "/api/v1/reports/snapshots/generate",
            json=payload,
            headers=auth_headers_admin
        )
        assert response.status_code == 200

        # Viewer should be forbidden
        response = await client.post(
            "/api/v1/reports/snapshots/generate",
            json=payload,
            headers=auth_headers_viewer
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_generate_daily_snapshot_api(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test generating daily snapshot via API."""
        # Create some tickets
        for i in range(3):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id
            )

        payload = {"period_type": "day"}

        response = await client.post(
            "/api/v1/reports/snapshots/generate",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert "snapshot" in data
        assert "message" in data
        assert data["snapshot"]["period_type"] == "day"

    @pytest.mark.asyncio
    async def test_generate_weekly_snapshot_api(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test generating weekly snapshot via API."""
        payload = {"period_type": "week"}

        response = await client.post(
            "/api/v1/reports/snapshots/generate",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["snapshot"]["period_type"] == "week"

    @pytest.mark.asyncio
    async def test_generate_monthly_snapshot_api(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test generating monthly snapshot via API."""
        payload = {"period_type": "month"}

        response = await client.post(
            "/api/v1/reports/snapshots/generate",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["snapshot"]["period_type"] == "month"

    @pytest.mark.asyncio
    async def test_generate_snapshot_with_target_date(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test generating snapshot for specific target date."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        payload = {
            "period_type": "day",
            "target_date": yesterday
        }

        response = await client.post(
            "/api/v1/reports/snapshots/generate",
            json=payload,
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["snapshot"]["period_start"] == yesterday


# -----------------------------------------------------------------------------
# Snapshot Deletion Tests
# -----------------------------------------------------------------------------

class TestSnapshotDeletion:
    """Tests for snapshot deletion."""

    @pytest.mark.asyncio
    async def test_delete_snapshot_admin_only(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        auth_headers_viewer: dict,
        db_session: AsyncSession,
        test_tenant: Tenant
    ):
        """Test that only admin can delete snapshots."""
        snapshot = await ReportSnapshotFactory.create(
            db_session,
            tenant_id=test_tenant.id
        )

        # Viewer should be forbidden
        response = await client.delete(
            f"/api/v1/reports/snapshots/{snapshot.id}",
            headers=auth_headers_viewer
        )
        assert response.status_code == 403

        # Admin should succeed
        response = await client.delete(
            f"/api/v1/reports/snapshots/{snapshot.id}",
            headers=auth_headers_admin
        )
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_snapshot_not_found(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test deleting non-existent snapshot returns 404."""
        response = await client.delete(
            "/api/v1/reports/snapshots/non-existent-id",
            headers=auth_headers_admin
        )

        assert response.status_code == 404


# -----------------------------------------------------------------------------
# Metrics Calculation Tests
# -----------------------------------------------------------------------------

class TestMetricsCalculation:
    """Tests for report metrics calculation."""

    @pytest.mark.asyncio
    async def test_metrics_by_status_breakdown(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test status breakdown in metrics."""
        statuses = [
            TicketStatus.NEW,
            TicketStatus.NEW,
            TicketStatus.ASSIGNED,
            TicketStatus.IN_PROGRESS,
            TicketStatus.RESOLVED
        ]

        for status in statuses:
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                status=status
            )

        service = ReportService(db_session)
        snapshot = await service.generate_daily_snapshot(
            tenant_id=test_tenant.id,
            target_date=date.today()
        )

        assert snapshot.metrics["by_status"]["new"] == 2
        assert snapshot.metrics["by_status"]["assigned"] == 1
        assert snapshot.metrics["by_status"]["in_progress"] == 1
        assert snapshot.metrics["by_status"]["resolved"] == 1

    @pytest.mark.asyncio
    async def test_metrics_by_priority_breakdown(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test priority breakdown in metrics."""
        priorities = [
            TicketPriority.CRITICAL,
            TicketPriority.HIGH,
            TicketPriority.HIGH,
            TicketPriority.MEDIUM,
            TicketPriority.LOW
        ]

        for priority in priorities:
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                priority=priority
            )

        service = ReportService(db_session)
        snapshot = await service.generate_daily_snapshot(
            tenant_id=test_tenant.id,
            target_date=date.today()
        )

        assert snapshot.metrics["by_priority"]["critical"] == 1
        assert snapshot.metrics["by_priority"]["high"] == 2
        assert snapshot.metrics["by_priority"]["medium"] == 1
        assert snapshot.metrics["by_priority"]["low"] == 1

    @pytest.mark.asyncio
    async def test_metrics_by_category_breakdown(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_site: Site,
        admin_user: User
    ):
        """Test category breakdown in metrics."""
        categories = [
            TicketCategory.HARDWARE,
            TicketCategory.HARDWARE,
            TicketCategory.SOFTWARE,
            TicketCategory.NETWORK,
            TicketCategory.POWER
        ]

        for category in categories:
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=test_site.id,
                created_by=admin_user.id,
                category=category
            )

        service = ReportService(db_session)
        snapshot = await service.generate_daily_snapshot(
            tenant_id=test_tenant.id,
            target_date=date.today()
        )

        assert snapshot.metrics["by_category"]["hardware"] == 2
        assert snapshot.metrics["by_category"]["software"] == 1
        assert snapshot.metrics["by_category"]["network"] == 1
        assert snapshot.metrics["by_category"]["power"] == 1

    @pytest.mark.asyncio
    async def test_metrics_top_sites(
        self,
        db_session: AsyncSession,
        test_tenant: Tenant,
        admin_user: User
    ):
        """Test top sites by ticket count in metrics."""
        # Create multiple sites
        site1 = await SiteFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            name="High Volume Site"
        )
        site2 = await SiteFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            name="Low Volume Site"
        )

        # Create more tickets for site1
        for i in range(5):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=site1.id,
                created_by=admin_user.id
            )

        # Create fewer tickets for site2
        for i in range(2):
            await TicketFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                site_id=site2.id,
                created_by=admin_user.id
            )

        service = ReportService(db_session)
        snapshot = await service.generate_daily_snapshot(
            tenant_id=test_tenant.id,
            target_date=date.today()
        )

        top_sites = snapshot.metrics["top_sites"]
        assert len(top_sites) >= 2
        # Site1 should be first (more tickets)
        assert top_sites[0]["site_name"] == "High Volume Site"
        assert top_sites[0]["ticket_count"] == 5


# -----------------------------------------------------------------------------
# Scheduler Status Tests
# -----------------------------------------------------------------------------

class TestSchedulerStatus:
    """Tests for report scheduler status endpoint."""

    @pytest.mark.asyncio
    async def test_get_scheduler_status_admin_only(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        auth_headers_viewer: dict
    ):
        """Test that only admin can view scheduler status."""
        # Admin should succeed
        response = await client.get(
            "/api/v1/reports/scheduler/status",
            headers=auth_headers_admin
        )
        assert response.status_code == 200

        # Viewer should be forbidden
        response = await client.get(
            "/api/v1/reports/scheduler/status",
            headers=auth_headers_viewer
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_scheduler_status_structure(
        self,
        client: AsyncClient,
        auth_headers_admin: dict
    ):
        """Test scheduler status response structure."""
        response = await client.get(
            "/api/v1/reports/scheduler/status",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "jobs" in data
