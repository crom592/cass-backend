"""
Sample data seeding script for TARDIS CASS system.
Creates realistic test data including sites, chargers, tickets, and report snapshots.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta, date
from decimal import Decimal
import random

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.asset import Site, Charger
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from app.models.report import ReportSnapshot, PeriodType
from app.services.report_service import ReportService
from app.core.security import get_password_hash


# Sample data configurations
TENANT_NAME = "Demo Tenant"
ADMIN_EMAIL = "admin@demo.com"
ADMIN_PASSWORD = "admin123"

SITES_DATA = [
    {"name": "강남역 충전소", "code": "GN001", "address": "서울시 강남구 강남대로 123", "lat": 37.4979, "lon": 127.0276},
    {"name": "홍대입구역 충전소", "code": "HD001", "address": "서울시 마포구 양화로 456", "lat": 37.5572, "lon": 126.9239},
    {"name": "판교테크노밸리 충전소", "code": "PG001", "address": "경기도 성남시 분당구 판교역로 789", "lat": 37.4012, "lon": 127.1084},
    {"name": "인천공항 충전소", "code": "IC001", "address": "인천시 중구 공항로 271", "lat": 37.4602, "lon": 126.4407},
    {"name": "부산역 충전소", "code": "BS001", "address": "부산시 동구 중앙대로 206", "lat": 35.1156, "lon": 129.0419},
]

CHARGER_MODELS = ["DC 100kW", "DC 50kW", "AC 7kW", "DC 200kW"]
CHARGER_STATUSES = ["Available", "Charging", "Faulted", "Unavailable"]

TICKET_TITLES = [
    "충전기 화면 터치 불량",
    "결제 시스템 오류",
    "충전 케이블 손상",
    "통신 연결 끊김",
    "과열 경고 발생",
    "충전 속도 저하",
    "인증 실패 오류",
    "디스플레이 화면 꺼짐",
    "충전 시작 불가",
    "비상 정지 버튼 작동 불량",
]

TICKET_DESCRIPTIONS = [
    "고객이 충전기 화면을 터치해도 반응이 없다고 신고했습니다.",
    "결제 승인 과정에서 시스템 오류가 발생합니다.",
    "충전 케이블에 외부 손상이 확인되었습니다.",
    "충전기가 서버와의 통신이 간헐적으로 끊깁니다.",
    "충전 중 과열 경고가 표시되고 충전이 중단됩니다.",
    "정상 충전 속도보다 현저히 낮은 속도로 충전됩니다.",
    "사용자 인증 과정에서 반복적으로 실패합니다.",
    "충전기 디스플레이가 갑자기 꺼지는 현상이 발생합니다.",
    "충전 케이블을 연결해도 충전이 시작되지 않습니다.",
    "비상 정지 버튼을 눌러도 반응이 없습니다.",
]


async def create_tenant_and_admin(db: AsyncSession):
    """Create demo tenant and admin user."""
    print("Creating tenant and admin user...")
    
    # Check if tenant exists
    from sqlalchemy import select
    result = await db.execute(select(Tenant).where(Tenant.name == TENANT_NAME))
    tenant = result.scalar_one_or_none()
    
    if not tenant:
        tenant = Tenant(
            name=TENANT_NAME,
            code="DEMO",
            contact_email="contact@demo.com",
            contact_phone="02-1234-5678",
            is_active=True
        )
        db.add(tenant)
        await db.flush()
        print(f"✓ Created tenant: {tenant.name}")
    else:
        print(f"✓ Tenant already exists: {tenant.name}")
    
    # Check if admin exists
    result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
    admin = result.scalar_one_or_none()
    
    if not admin:
        admin = User(
            email=ADMIN_EMAIL,
            hashed_password=get_password_hash(ADMIN_PASSWORD),
            full_name="Demo Admin",
            role=UserRole.ADMIN,
            tenant_id=tenant.id,
            is_active=True
        )
        db.add(admin)
        await db.flush()
        print(f"✓ Created admin user: {admin.email}")
    else:
        print(f"✓ Admin user already exists: {admin.email}")
    
    await db.commit()
    return tenant, admin


async def create_sites_and_chargers(db: AsyncSession, tenant_id: str):
    """Create sample sites and chargers."""
    print("\nCreating sites and chargers...")
    
    from sqlalchemy import select
    sites = []
    
    for site_data in SITES_DATA:
        # Check if site exists
        result = await db.execute(
            select(Site).where(Site.code == site_data["code"], Site.tenant_id == tenant_id)
        )
        site = result.scalar_one_or_none()
        
        if not site:
            site = Site(
                tenant_id=tenant_id,
                name=site_data["name"],
                code=site_data["code"],
                address=site_data["address"],
                latitude=str(site_data["lat"]),
                longitude=str(site_data["lon"]),
                is_active=True
            )
            db.add(site)
            await db.flush()
            print(f"  ✓ Created site: {site.name}")
        else:
            print(f"  ✓ Site already exists: {site.name}")
        
        sites.append(site)
        
        # Create 2-4 chargers per site
        num_chargers = random.randint(2, 4)
        for i in range(num_chargers):
            charger_id = f"{site.code}-{i+1:02d}"
            
            result = await db.execute(
                select(Charger).where(Charger.csms_charger_id == charger_id)
            )
            charger = result.scalar_one_or_none()
            
            if not charger:
                charger = Charger(
                    name=f"Charger {i+1}",
                    serial_number=f"SN{random.randint(100000, 999999)}",
                    tenant_id=tenant_id,
                    site_id=site.id,
                    model=random.choice(CHARGER_MODELS),
                    firmware_version=f"v{random.randint(1, 3)}.{random.randint(0, 9)}.{random.randint(0, 9)}",
                    current_status=random.choice(CHARGER_STATUSES),
                    csms_charger_id=charger_id,
                    is_active=True
                )
                db.add(charger)
                print(f"    ✓ Created charger: {charger.csms_charger_id}")
    
    await db.commit()
    print(f"✓ Created {len(sites)} sites with chargers")
    return sites


async def create_tickets(db: AsyncSession, tenant_id: str, admin_id: str, sites: list, num_tickets: int = 50):
    """Create sample tickets with realistic data."""
    print(f"\nCreating {num_tickets} sample tickets...")
    
    from sqlalchemy import select
    
    # Get all chargers
    result = await db.execute(select(Charger))
    chargers = result.scalars().all()
    
    if not chargers:
        print("  ✗ No chargers found. Cannot create tickets.")
        return []
    
    tickets = []
    now = datetime.utcnow()
    
    for i in range(num_tickets):
        # Random date within last 60 days
        days_ago = random.randint(0, 60)
        created_at = now - timedelta(days=days_ago, hours=random.randint(0, 23), minutes=random.randint(0, 59))
        
        # Random status with realistic distribution
        # new, assigned, in_progress, pending_customer, pending_vendor, resolved, closed, cancelled
        status_weights = [0.1, 0.15, 0.2, 0.05, 0.05, 0.3, 0.1, 0.05]
        status = random.choices(list(TicketStatus), weights=status_weights)[0]
        
        # Random priority with realistic distribution
        priority_weights = [0.05, 0.15, 0.5, 0.3]  # critical, high, medium, low
        priority = random.choices(list(TicketPriority), weights=priority_weights)[0]
        
        # Random category
        category = random.choice(list(TicketCategory))
        
        # Random title and description
        title_idx = random.randint(0, len(TICKET_TITLES) - 1)
        title = TICKET_TITLES[title_idx]
        description = TICKET_DESCRIPTIONS[title_idx]
        
        # Random charger
        charger = random.choice(chargers)
        
        # Calculate timestamps based on status
        opened_at = created_at
        closed_at = None
        
        if status in [TicketStatus.RESOLVED, TicketStatus.CLOSED]:
            # Resolved/closed tickets have resolution time
            resolution_hours = random.randint(1, 48)
            closed_at = opened_at + timedelta(hours=resolution_hours)
        
        # SLA breach (10% chance)
        sla_breached = random.random() < 0.1
        
        from app.models.ticket import TicketChannel
        
        ticket = Ticket(
            tenant_id=tenant_id,
            ticket_number=f"TK{now.year}{(i+1):05d}",
            title=title,
            description=description,
            channel=random.choice(list(TicketChannel)),
            current_status=status,
            priority=priority,
            category=category,
            charger_id=charger.id,
            site_id=charger.site_id,
            created_by=admin_id,
            opened_at=opened_at,
            closed_at=closed_at,
            sla_breached=sla_breached,
            created_at=created_at,
            updated_at=created_at if status == TicketStatus.NEW else created_at + timedelta(hours=random.randint(1, 24))
        )
        
        db.add(ticket)
        tickets.append(ticket)
        
        if (i + 1) % 10 == 0:
            print(f"  ✓ Created {i + 1}/{num_tickets} tickets...")
    
    await db.commit()
    print(f"✓ Created {len(tickets)} tickets")
    return tickets


async def generate_report_snapshots(db: AsyncSession, tenant_id: str):
    """Generate report snapshots for the last 30 days."""
    print("\nGenerating report snapshots...")
    
    report_service = ReportService(db)
    today = date.today()
    
    # Generate daily snapshots for last 30 days
    for days_ago in range(30, 0, -1):
        target_date = today - timedelta(days=days_ago)
        try:
            snapshot = await report_service.generate_daily_snapshot(
                tenant_id=tenant_id,
                target_date=target_date
            )
            if (30 - days_ago + 1) % 5 == 0:
                print(f"  ✓ Generated {30 - days_ago + 1}/30 daily snapshots...")
        except Exception as e:
            print(f"  ✗ Failed to generate snapshot for {target_date}: {str(e)}")
    
    print("✓ Generated daily snapshots for last 30 days")
    
    # Generate weekly snapshots for last 4 weeks
    for weeks_ago in range(4, 0, -1):
        week_start = today - timedelta(days=today.weekday() + 7 * weeks_ago)
        try:
            snapshot = await report_service.generate_weekly_snapshot(
                tenant_id=tenant_id,
                week_start=week_start
            )
            print(f"  ✓ Generated weekly snapshot for week starting {week_start}")
        except Exception as e:
            print(f"  ✗ Failed to generate weekly snapshot: {str(e)}")
    
    # Generate monthly snapshots for last 3 months
    for months_ago in range(3, 0, -1):
        target_month = today - timedelta(days=30 * months_ago)
        try:
            snapshot = await report_service.generate_monthly_snapshot(
                tenant_id=tenant_id,
                year=target_month.year,
                month=target_month.month
            )
            print(f"  ✓ Generated monthly snapshot for {target_month.year}-{target_month.month:02d}")
        except Exception as e:
            print(f"  ✗ Failed to generate monthly snapshot: {str(e)}")
    
    print("✓ Generated all report snapshots")


async def main():
    """Main seeding function."""
    print("=" * 60)
    print("TARDIS CASS - Sample Data Seeding Script")
    print("=" * 60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Create tenant and admin
            tenant, admin = await create_tenant_and_admin(db)
            
            # Create sites and chargers
            sites = await create_sites_and_chargers(db, tenant.id)
            
            # Create tickets
            tickets = await create_tickets(db, tenant.id, admin.id, sites, num_tickets=100)
            
            # Generate report snapshots
            await generate_report_snapshots(db, tenant.id)
            
            print("\n" + "=" * 60)
            print("✓ Sample data seeding completed successfully!")
            print("=" * 60)
            print(f"\nLogin credentials:")
            print(f"  Email: {ADMIN_EMAIL}")
            print(f"  Password: {ADMIN_PASSWORD}")
            print(f"\nCreated:")
            print(f"  - 1 tenant: {tenant.name}")
            print(f"  - 1 admin user")
            print(f"  - {len(sites)} sites")
            print(f"  - Multiple chargers")
            print(f"  - {len(tickets)} tickets")
            print(f"  - Report snapshots (daily, weekly, monthly)")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n✗ Error during seeding: {str(e)}")
            import traceback
            traceback.print_exc()
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
