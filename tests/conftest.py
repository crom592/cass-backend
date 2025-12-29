"""
CASS Backend Test Configuration

Provides shared fixtures for async testing with:
- In-memory SQLite database
- Test client with async support
- Authenticated user fixtures (admin, engineer, viewer)
- Sample data factories for tickets, SLA policies, etc.
"""
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, Any
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_password_hash, create_access_token
from app.main import app
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.ticket import (
    Ticket, TicketStatus, TicketPriority, TicketCategory, TicketChannel,
    TicketStatusHistory
)
from app.models.sla import SlaPolicy, SlaMeasurement, SlaStatus
from app.models.asset import Site, Charger
from app.models.worklog import Worklog, WorkType
from app.models.report import ReportSnapshot, PeriodType


# Test database URL - SQLite in-memory with async support
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def async_engine():
    """Create an async engine for testing with in-memory SQLite."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False}
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test."""
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with database override."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# Data Factories
# -----------------------------------------------------------------------------

class TenantFactory:
    """Factory for creating test tenants."""

    @staticmethod
    async def create(
        db: AsyncSession,
        name: str = "Test Tenant",
        code: str = None
    ) -> Tenant:
        tenant = Tenant(
            id=str(uuid.uuid4()),
            name=name,
            code=code or f"TEST-{uuid.uuid4().hex[:6].upper()}",
            contact_name="Test Contact",
            contact_email="contact@test.com",
            is_active=True
        )
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
        return tenant


class UserFactory:
    """Factory for creating test users."""

    @staticmethod
    async def create(
        db: AsyncSession,
        tenant_id: str,
        email: str = None,
        role: UserRole = UserRole.VIEWER,
        password: str = "testpassword123",
        is_active: bool = True
    ) -> User:
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=email or f"user-{uuid.uuid4().hex[:8]}@test.com",
            hashed_password=get_password_hash(password),
            role=role,
            full_name=f"Test {role.value.replace('_', ' ').title()}",
            is_active=is_active,
            is_verified=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


class SiteFactory:
    """Factory for creating test sites."""

    @staticmethod
    async def create(
        db: AsyncSession,
        tenant_id: str,
        name: str = "Test Site",
        code: str = None
    ) -> Site:
        site = Site(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            code=code or f"SITE-{uuid.uuid4().hex[:6].upper()}",
            address="123 Test Street",
            city="Test City",
            is_active=True
        )
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


class ChargerFactory:
    """Factory for creating test chargers."""

    @staticmethod
    async def create(
        db: AsyncSession,
        tenant_id: str,
        site_id: str,
        name: str = "Test Charger",
        csms_charger_id: str = None
    ) -> Charger:
        charger = Charger(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            site_id=site_id,
            name=name,
            serial_number=f"SN-{uuid.uuid4().hex[:8].upper()}",
            csms_charger_id=csms_charger_id or f"CSMS-{uuid.uuid4().hex[:8].upper()}",
            vendor="Test Vendor",
            model="Test Model",
            power_kw=150,
            connector_count=2,
            is_active=True
        )
        db.add(charger)
        await db.commit()
        await db.refresh(charger)
        return charger


class TicketFactory:
    """Factory for creating test tickets."""

    @staticmethod
    async def create(
        db: AsyncSession,
        tenant_id: str,
        site_id: str,
        created_by: str,
        charger_id: str = None,
        title: str = "Test Ticket",
        status: TicketStatus = TicketStatus.NEW,
        priority: TicketPriority = TicketPriority.MEDIUM,
        category: TicketCategory = TicketCategory.HARDWARE,
        channel: TicketChannel = TicketChannel.WEB,
        sla_breached: bool = False,
        opened_at: datetime = None
    ) -> Ticket:
        ticket = Ticket(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            site_id=site_id,
            charger_id=charger_id,
            ticket_number=f"TKT-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
            title=title,
            description="Test ticket description",
            channel=channel,
            category=category,
            priority=priority,
            current_status=status,
            created_by=created_by,
            opened_at=opened_at or datetime.utcnow(),
            sla_breached=sla_breached
        )
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)
        return ticket


class SlaPolicyFactory:
    """Factory for creating test SLA policies."""

    @staticmethod
    async def create(
        db: AsyncSession,
        tenant_id: str,
        category: str = "hardware",
        priority: str = "medium",
        response_time_minutes: int = 60,
        resolution_time_minutes: int = 480
    ) -> SlaPolicy:
        policy = SlaPolicy(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            category=category,
            priority=priority,
            response_time_minutes=response_time_minutes,
            resolution_time_minutes=resolution_time_minutes,
            is_active=True
        )
        db.add(policy)
        await db.commit()
        await db.refresh(policy)
        return policy


class SlaMeasurementFactory:
    """Factory for creating test SLA measurements."""

    @staticmethod
    async def create(
        db: AsyncSession,
        ticket_id: str,
        policy_id: str,
        status: SlaStatus = SlaStatus.ACTIVE,
        response_breached: bool = False,
        resolution_breached: bool = False
    ) -> SlaMeasurement:
        now = datetime.utcnow()
        measurement = SlaMeasurement(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            policy_id=policy_id,
            status=status,
            response_target_at=now + timedelta(hours=1),
            resolution_target_at=now + timedelta(hours=8),
            response_breached=response_breached,
            resolution_breached=resolution_breached,
            started_at=now
        )
        db.add(measurement)
        await db.commit()
        await db.refresh(measurement)
        return measurement


class ReportSnapshotFactory:
    """Factory for creating test report snapshots."""

    @staticmethod
    async def create(
        db: AsyncSession,
        tenant_id: str,
        period_type: PeriodType = PeriodType.DAY,
        metrics: Dict[str, Any] = None
    ) -> ReportSnapshot:
        from datetime import date

        today = date.today()

        if metrics is None:
            metrics = {
                "total_created": 10,
                "total_resolved": 5,
                "total_closed": 3,
                "by_status": {"new": 3, "assigned": 2, "closed": 5},
                "by_priority": {"critical": 1, "high": 2, "medium": 4, "low": 3},
                "by_category": {"hardware": 4, "software": 3, "network": 3},
                "avg_resolution_time_hours": 4.5,
                "sla_compliance_rate": 0.9,
                "sla_breached_count": 1,
                "top_sites": [],
                "period_start": today.isoformat(),
                "period_end": today.isoformat(),
                "generated_at": datetime.utcnow().isoformat()
            }

        snapshot = ReportSnapshot(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            period_type=period_type,
            period_start=today,
            period_end=today,
            metrics=metrics
        )
        db.add(snapshot)
        await db.commit()
        await db.refresh(snapshot)
        return snapshot


class WorklogFactory:
    """Factory for creating test worklogs."""

    @staticmethod
    async def create(
        db: AsyncSession,
        ticket_id: str,
        author_id: str,
        body: str = "Test worklog entry",
        work_type: WorkType = WorkType.OTHER,
        is_internal: bool = False,
        time_spent_minutes: int = 30
    ) -> Worklog:
        # Note: is_internal in model is defined as String, not Boolean
        # Converting to string for compatibility
        worklog = Worklog(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            author_id=author_id,
            body=body,
            work_type=work_type,
            is_internal=str(is_internal) if isinstance(is_internal, bool) else is_internal,
            time_spent_minutes=time_spent_minutes
        )
        db.add(worklog)
        await db.commit()
        await db.refresh(worklog)
        return worklog


# -----------------------------------------------------------------------------
# Pre-configured Test Data Fixtures
# -----------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_tenant(db_session: AsyncSession) -> Tenant:
    """Create a test tenant."""
    return await TenantFactory.create(db_session, name="CASS Test Tenant")


@pytest_asyncio.fixture
async def test_site(db_session: AsyncSession, test_tenant: Tenant) -> Site:
    """Create a test site."""
    return await SiteFactory.create(db_session, tenant_id=test_tenant.id)


@pytest_asyncio.fixture
async def test_charger(db_session: AsyncSession, test_tenant: Tenant, test_site: Site) -> Charger:
    """Create a test charger."""
    return await ChargerFactory.create(
        db_session,
        tenant_id=test_tenant.id,
        site_id=test_site.id
    )


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """Create an admin test user."""
    return await UserFactory.create(
        db_session,
        tenant_id=test_tenant.id,
        email="admin@test.com",
        role=UserRole.ADMIN
    )


@pytest_asyncio.fixture
async def engineer_user(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """Create an engineer test user."""
    return await UserFactory.create(
        db_session,
        tenant_id=test_tenant.id,
        email="engineer@test.com",
        role=UserRole.AS_ENGINEER
    )


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """Create a viewer test user."""
    return await UserFactory.create(
        db_session,
        tenant_id=test_tenant.id,
        email="viewer@test.com",
        role=UserRole.VIEWER
    )


@pytest_asyncio.fixture
async def admin_token(admin_user: User) -> str:
    """Get JWT token for admin user."""
    return create_access_token(
        data={"sub": admin_user.id, "email": admin_user.email, "role": admin_user.role.value}
    )


@pytest_asyncio.fixture
async def engineer_token(engineer_user: User) -> str:
    """Get JWT token for engineer user."""
    return create_access_token(
        data={"sub": engineer_user.id, "email": engineer_user.email, "role": engineer_user.role.value}
    )


@pytest_asyncio.fixture
async def viewer_token(viewer_user: User) -> str:
    """Get JWT token for viewer user."""
    return create_access_token(
        data={"sub": viewer_user.id, "email": viewer_user.email, "role": viewer_user.role.value}
    )


@pytest_asyncio.fixture
async def auth_headers_admin(admin_token: str) -> Dict[str, str]:
    """Get auth headers for admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def auth_headers_engineer(engineer_token: str) -> Dict[str, str]:
    """Get auth headers for engineer user."""
    return {"Authorization": f"Bearer {engineer_token}"}


@pytest_asyncio.fixture
async def auth_headers_viewer(viewer_token: str) -> Dict[str, str]:
    """Get auth headers for viewer user."""
    return {"Authorization": f"Bearer {viewer_token}"}


@pytest_asyncio.fixture
async def test_ticket(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_site: Site,
    admin_user: User
) -> Ticket:
    """Create a test ticket."""
    return await TicketFactory.create(
        db_session,
        tenant_id=test_tenant.id,
        site_id=test_site.id,
        created_by=admin_user.id
    )


@pytest_asyncio.fixture
async def test_sla_policy(db_session: AsyncSession, test_tenant: Tenant) -> SlaPolicy:
    """Create a test SLA policy."""
    return await SlaPolicyFactory.create(db_session, tenant_id=test_tenant.id)


# Export factories for use in tests
__all__ = [
    "TenantFactory",
    "UserFactory",
    "SiteFactory",
    "ChargerFactory",
    "TicketFactory",
    "SlaPolicyFactory",
    "SlaMeasurementFactory",
    "ReportSnapshotFactory",
    "WorklogFactory",
]
