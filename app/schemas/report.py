from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import date, datetime
from enum import Enum


class PeriodType(str, Enum):
    """Period types for report snapshots."""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class ReportSummaryResponse(BaseModel):
    """Response schema for real-time report summary."""
    total_tickets: int
    by_status: Dict[str, int]
    by_priority: Dict[str, int]
    by_category: Dict[str, int]
    avg_resolution_time_hours: float
    sla_breached: int
    sla_compliance_rate: float


# Snapshot Schemas

class TopSiteInfo(BaseModel):
    """Information about a top site by ticket count."""
    site_id: str
    site_name: str
    site_code: str
    ticket_count: int


class SnapshotMetrics(BaseModel):
    """Metrics stored in a report snapshot."""
    total_created: int = Field(description="Total tickets created in period")
    total_resolved: int = Field(description="Total tickets resolved in period")
    total_closed: int = Field(description="Total tickets closed in period")
    by_status: Dict[str, int] = Field(description="Breakdown by current status")
    by_priority: Dict[str, int] = Field(description="Breakdown by priority")
    by_category: Dict[str, int] = Field(description="Breakdown by category")
    avg_resolution_time_hours: float = Field(description="Average resolution time in hours")
    sla_compliance_rate: float = Field(description="SLA compliance rate (0-1)")
    sla_breached_count: int = Field(description="Number of SLA breaches")
    top_sites: List[TopSiteInfo] = Field(description="Top sites by ticket count")
    period_start: str = Field(description="Period start datetime (ISO format)")
    period_end: str = Field(description="Period end datetime (ISO format)")
    generated_at: str = Field(description="Snapshot generation datetime (ISO format)")


class SnapshotBase(BaseModel):
    """Base schema for snapshot data."""
    period_type: PeriodType
    period_start: date
    period_end: date


class SnapshotCreate(BaseModel):
    """Schema for manual snapshot generation request."""
    period_type: PeriodType = Field(description="Type of period: day, week, or month")
    target_date: Optional[date] = Field(
        None,
        description="Target date for snapshot. For day: specific date. "
                    "For week: any date in the week. For month: any date in the month. "
                    "Defaults to previous period if not specified."
    )


class SnapshotResponse(SnapshotBase):
    """Response schema for a report snapshot."""
    id: str
    tenant_id: str
    metrics: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SnapshotDetailResponse(SnapshotResponse):
    """Detailed response schema with parsed metrics."""
    parsed_metrics: Optional[SnapshotMetrics] = None

    @classmethod
    def from_snapshot(cls, snapshot) -> "SnapshotDetailResponse":
        """Create a detailed response from a snapshot model."""
        parsed = None
        if snapshot.metrics:
            try:
                # Parse top_sites properly
                top_sites = []
                for site in snapshot.metrics.get("top_sites", []):
                    top_sites.append(TopSiteInfo(**site))

                parsed = SnapshotMetrics(
                    total_created=snapshot.metrics.get("total_created", 0),
                    total_resolved=snapshot.metrics.get("total_resolved", 0),
                    total_closed=snapshot.metrics.get("total_closed", 0),
                    by_status=snapshot.metrics.get("by_status", {}),
                    by_priority=snapshot.metrics.get("by_priority", {}),
                    by_category=snapshot.metrics.get("by_category", {}),
                    avg_resolution_time_hours=snapshot.metrics.get("avg_resolution_time_hours", 0),
                    sla_compliance_rate=snapshot.metrics.get("sla_compliance_rate", 1.0),
                    sla_breached_count=snapshot.metrics.get("sla_breached_count", 0),
                    top_sites=top_sites,
                    period_start=snapshot.metrics.get("period_start", ""),
                    period_end=snapshot.metrics.get("period_end", ""),
                    generated_at=snapshot.metrics.get("generated_at", "")
                )
            except Exception:
                parsed = None

        return cls(
            id=snapshot.id,
            tenant_id=snapshot.tenant_id,
            period_type=snapshot.period_type,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            metrics=snapshot.metrics,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            parsed_metrics=parsed
        )


class SnapshotListResponse(BaseModel):
    """Response schema for paginated snapshot list."""
    items: List[SnapshotResponse]
    total: int
    skip: int
    limit: int


class SnapshotGenerateResponse(BaseModel):
    """Response schema for snapshot generation."""
    snapshot: SnapshotResponse
    message: str


class JobStatusResponse(BaseModel):
    """Response schema for batch job status."""
    job_type: str
    status: str
    success_count: int = 0
    failure_count: int = 0
    errors: List[str] = []
    completed_at: Optional[str] = None


class SchedulerStatusResponse(BaseModel):
    """Response schema for scheduler status."""
    status: str
    jobs: List[Dict[str, Any]]


# New schemas for frontend integration

class ReportStatsResponse(BaseModel):
    """Response schema for report statistics."""
    total_tickets: int = Field(description="Total tickets in period")
    total_trend: float = Field(description="Percentage change from previous period")
    resolved_count: int = Field(description="Number of resolved tickets")
    resolved_trend: float = Field(description="Percentage change in resolved tickets")
    sla_breach_rate: float = Field(description="SLA breach rate as percentage")
    sla_trend: float = Field(description="Percentage change in SLA breach rate")
    avg_resolution_time: float = Field(description="Average resolution time in hours")
    time_trend: float = Field(description="Percentage change in resolution time")


class ReportTrendsResponse(BaseModel):
    """Response schema for ticket trends over time."""
    labels: List[str] = Field(description="Date labels for the trend")
    values: List[int] = Field(description="Ticket counts for each date")


class DistributionItem(BaseModel):
    """Single item in a distribution breakdown."""
    name: str = Field(description="Category/Priority/Status name")
    count: int = Field(description="Number of tickets")
    percentage: float = Field(description="Percentage of total")


class ReportDistributionResponse(BaseModel):
    """Response schema for ticket distribution."""
    by_category: List[DistributionItem] = Field(description="Distribution by category")
    by_priority: List[DistributionItem] = Field(description="Distribution by priority")


class SnapshotTableRow(BaseModel):
    """Single row in the snapshots table."""
    date: str = Field(description="Snapshot date")
    total: int = Field(description="Total tickets")
    resolved: int = Field(description="Resolved tickets")
    breached: int = Field(description="SLA breached tickets")
    avgTime: int = Field(description="Average resolution time in minutes")


class ReportSnapshotsResponse(BaseModel):
    """Response schema for recent snapshots table."""
    snapshots: List[SnapshotTableRow] = Field(description="List of snapshot rows")
