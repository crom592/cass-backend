"""
Report Snapshot Service

Provides methods for generating daily, weekly, and monthly report snapshots
with ticket aggregation metrics for the CASS system.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from app.models.report import ReportSnapshot, PeriodType
from app.models.asset import Site

logger = logging.getLogger(__name__)


class ReportService:
    """Service for generating and managing report snapshots."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_daily_snapshot(
        self,
        tenant_id: str,
        target_date: date
    ) -> ReportSnapshot:
        """
        Generate a daily snapshot for the specified date.

        Args:
            tenant_id: The tenant ID to generate snapshot for
            target_date: The date to generate snapshot for

        Returns:
            ReportSnapshot: The generated snapshot record
        """
        period_start = target_date
        period_end = target_date

        # Check if snapshot already exists
        existing = await self._get_existing_snapshot(
            tenant_id, PeriodType.DAY, period_start, period_end
        )
        if existing:
            logger.info(
                f"Updating existing daily snapshot for tenant {tenant_id}, date {target_date}"
            )
            snapshot = existing
        else:
            snapshot = ReportSnapshot(
                tenant_id=tenant_id,
                period_type=PeriodType.DAY,
                period_start=period_start,
                period_end=period_end,
            )

        # Generate metrics
        metrics = await self._calculate_metrics(
            tenant_id,
            datetime.combine(period_start, datetime.min.time()),
            datetime.combine(period_end, datetime.max.time())
        )

        snapshot.metrics = metrics
        snapshot.updated_at = datetime.utcnow()

        if not existing:
            self.db.add(snapshot)

        await self.db.commit()
        await self.db.refresh(snapshot)

        logger.info(
            f"Generated daily snapshot {snapshot.id} for tenant {tenant_id}, "
            f"date {target_date}, total_tickets={metrics.get('total_created', 0)}"
        )

        return snapshot

    async def generate_weekly_snapshot(
        self,
        tenant_id: str,
        week_start: date
    ) -> ReportSnapshot:
        """
        Generate a weekly snapshot starting from the specified date.

        Args:
            tenant_id: The tenant ID to generate snapshot for
            week_start: The Monday of the week to generate snapshot for

        Returns:
            ReportSnapshot: The generated snapshot record
        """
        # Ensure week_start is a Monday
        days_since_monday = week_start.weekday()
        if days_since_monday != 0:
            week_start = week_start - timedelta(days=days_since_monday)

        period_start = week_start
        period_end = week_start + timedelta(days=6)

        # Check if snapshot already exists
        existing = await self._get_existing_snapshot(
            tenant_id, PeriodType.WEEK, period_start, period_end
        )
        if existing:
            logger.info(
                f"Updating existing weekly snapshot for tenant {tenant_id}, "
                f"week starting {week_start}"
            )
            snapshot = existing
        else:
            snapshot = ReportSnapshot(
                tenant_id=tenant_id,
                period_type=PeriodType.WEEK,
                period_start=period_start,
                period_end=period_end,
            )

        # Generate metrics
        metrics = await self._calculate_metrics(
            tenant_id,
            datetime.combine(period_start, datetime.min.time()),
            datetime.combine(period_end, datetime.max.time())
        )

        snapshot.metrics = metrics
        snapshot.updated_at = datetime.utcnow()

        if not existing:
            self.db.add(snapshot)

        await self.db.commit()
        await self.db.refresh(snapshot)

        logger.info(
            f"Generated weekly snapshot {snapshot.id} for tenant {tenant_id}, "
            f"week {week_start} to {period_end}, total_tickets={metrics.get('total_created', 0)}"
        )

        return snapshot

    async def generate_monthly_snapshot(
        self,
        tenant_id: str,
        year: int,
        month: int
    ) -> ReportSnapshot:
        """
        Generate a monthly snapshot for the specified month.

        Args:
            tenant_id: The tenant ID to generate snapshot for
            year: The year
            month: The month (1-12)

        Returns:
            ReportSnapshot: The generated snapshot record
        """
        period_start = date(year, month, 1)

        # Calculate last day of month
        if month == 12:
            next_month_start = date(year + 1, 1, 1)
        else:
            next_month_start = date(year, month + 1, 1)
        period_end = next_month_start - timedelta(days=1)

        # Check if snapshot already exists
        existing = await self._get_existing_snapshot(
            tenant_id, PeriodType.MONTH, period_start, period_end
        )
        if existing:
            logger.info(
                f"Updating existing monthly snapshot for tenant {tenant_id}, "
                f"month {year}-{month:02d}"
            )
            snapshot = existing
        else:
            snapshot = ReportSnapshot(
                tenant_id=tenant_id,
                period_type=PeriodType.MONTH,
                period_start=period_start,
                period_end=period_end,
            )

        # Generate metrics
        metrics = await self._calculate_metrics(
            tenant_id,
            datetime.combine(period_start, datetime.min.time()),
            datetime.combine(period_end, datetime.max.time())
        )

        snapshot.metrics = metrics
        snapshot.updated_at = datetime.utcnow()

        if not existing:
            self.db.add(snapshot)

        await self.db.commit()
        await self.db.refresh(snapshot)

        logger.info(
            f"Generated monthly snapshot {snapshot.id} for tenant {tenant_id}, "
            f"month {year}-{month:02d}, total_tickets={metrics.get('total_created', 0)}"
        )

        return snapshot

    async def _get_existing_snapshot(
        self,
        tenant_id: str,
        period_type: PeriodType,
        period_start: date,
        period_end: date
    ) -> Optional[ReportSnapshot]:
        """Check if a snapshot already exists for the given period."""
        query = select(ReportSnapshot).where(
            and_(
                ReportSnapshot.tenant_id == tenant_id,
                ReportSnapshot.period_type == period_type,
                ReportSnapshot.period_start == period_start,
                ReportSnapshot.period_end == period_end
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _calculate_metrics(
        self,
        tenant_id: str,
        start_datetime: datetime,
        end_datetime: datetime
    ) -> Dict[str, Any]:
        """
        Calculate all metrics for the given period.

        Returns a dictionary containing:
        - total_created: Total tickets created in period
        - total_resolved: Total tickets resolved in period
        - total_closed: Total tickets closed in period
        - by_status: Breakdown by current status
        - by_priority: Breakdown by priority
        - by_category: Breakdown by category
        - avg_resolution_time_hours: Average time to resolution
        - sla_compliance_rate: Percentage of tickets within SLA
        - sla_breached_count: Number of SLA breaches
        - top_sites: Sites with highest ticket counts
        """
        # Get tickets created in this period
        created_query = select(Ticket).where(
            and_(
                Ticket.tenant_id == tenant_id,
                Ticket.created_at >= start_datetime,
                Ticket.created_at <= end_datetime
            )
        )
        created_result = await self.db.execute(created_query)
        created_tickets = created_result.scalars().all()

        # Get tickets resolved in this period
        resolved_query = select(func.count(Ticket.id)).where(
            and_(
                Ticket.tenant_id == tenant_id,
                Ticket.resolved_at >= start_datetime,
                Ticket.resolved_at <= end_datetime
            )
        )
        resolved_result = await self.db.execute(resolved_query)
        total_resolved = resolved_result.scalar() or 0

        # Get tickets closed in this period
        closed_query = select(func.count(Ticket.id)).where(
            and_(
                Ticket.tenant_id == tenant_id,
                Ticket.closed_at >= start_datetime,
                Ticket.closed_at <= end_datetime
            )
        )
        closed_result = await self.db.execute(closed_query)
        total_closed = closed_result.scalar() or 0

        # Calculate breakdowns
        by_status: Dict[str, int] = {}
        by_priority: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        site_counts: Dict[str, int] = {}
        sla_breached_count = 0
        resolution_times: List[float] = []

        for ticket in created_tickets:
            # Status breakdown
            status_key = ticket.current_status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            # Priority breakdown
            priority_key = ticket.priority.value
            by_priority[priority_key] = by_priority.get(priority_key, 0) + 1

            # Category breakdown
            category_key = ticket.category.value
            by_category[category_key] = by_category.get(category_key, 0) + 1

            # Site counts
            site_counts[ticket.site_id] = site_counts.get(ticket.site_id, 0) + 1

            # SLA breaches
            if ticket.sla_breached:
                sla_breached_count += 1

            # Resolution time (for resolved tickets)
            if ticket.resolved_at and ticket.opened_at:
                resolution_hours = (
                    ticket.resolved_at - ticket.opened_at
                ).total_seconds() / 3600
                resolution_times.append(resolution_hours)

        total_created = len(created_tickets)

        # Calculate average resolution time
        avg_resolution_time = 0.0
        if resolution_times:
            avg_resolution_time = round(
                sum(resolution_times) / len(resolution_times), 2
            )

        # Calculate SLA compliance rate
        sla_compliance_rate = 1.0
        if total_created > 0:
            sla_compliance_rate = round(
                1 - (sla_breached_count / total_created), 4
            )

        # Get top sites by ticket count
        top_sites = await self._get_top_sites(tenant_id, site_counts, limit=10)

        return {
            "total_created": total_created,
            "total_resolved": total_resolved,
            "total_closed": total_closed,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_category": by_category,
            "avg_resolution_time_hours": avg_resolution_time,
            "sla_compliance_rate": sla_compliance_rate,
            "sla_breached_count": sla_breached_count,
            "top_sites": top_sites,
            "period_start": start_datetime.isoformat(),
            "period_end": end_datetime.isoformat(),
            "generated_at": datetime.utcnow().isoformat()
        }

    async def _get_top_sites(
        self,
        tenant_id: str,
        site_counts: Dict[str, int],
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get top sites by ticket count with site details."""
        if not site_counts:
            return []

        # Sort by count descending
        sorted_sites = sorted(
            site_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]

        top_sites = []
        site_ids = [s[0] for s in sorted_sites]

        # Fetch site details
        if site_ids:
            sites_query = select(Site).where(Site.id.in_(site_ids))
            sites_result = await self.db.execute(sites_query)
            sites = {s.id: s for s in sites_result.scalars().all()}

            for site_id, count in sorted_sites:
                site = sites.get(site_id)
                top_sites.append({
                    "site_id": site_id,
                    "site_name": site.name if site else "Unknown",
                    "site_code": site.code if site else "N/A",
                    "ticket_count": count
                })

        return top_sites

    async def get_snapshot_by_id(
        self,
        snapshot_id: str,
        tenant_id: str
    ) -> Optional[ReportSnapshot]:
        """Get a specific snapshot by ID."""
        query = select(ReportSnapshot).where(
            and_(
                ReportSnapshot.id == snapshot_id,
                ReportSnapshot.tenant_id == tenant_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_snapshots(
        self,
        tenant_id: str,
        period_type: Optional[PeriodType] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[ReportSnapshot], int]:
        """
        List snapshots with optional filters.

        Returns:
            Tuple of (snapshots list, total count)
        """
        # Build base query
        base_conditions = [ReportSnapshot.tenant_id == tenant_id]

        if period_type:
            base_conditions.append(ReportSnapshot.period_type == period_type)

        if from_date:
            base_conditions.append(ReportSnapshot.period_start >= from_date)

        if to_date:
            base_conditions.append(ReportSnapshot.period_end <= to_date)

        # Get total count
        count_query = select(func.count(ReportSnapshot.id)).where(
            and_(*base_conditions)
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Get paginated results
        query = (
            select(ReportSnapshot)
            .where(and_(*base_conditions))
            .order_by(ReportSnapshot.period_start.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        snapshots = result.scalars().all()

        return list(snapshots), total

    async def delete_snapshot(
        self,
        snapshot_id: str,
        tenant_id: str
    ) -> bool:
        """Delete a snapshot by ID."""
        snapshot = await self.get_snapshot_by_id(snapshot_id, tenant_id)
        if not snapshot:
            return False

        await self.db.delete(snapshot)
        await self.db.commit()
        return True
