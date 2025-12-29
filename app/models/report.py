from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Enum as SQLEnum, Date
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class PeriodType(str, enum.Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class ReportSnapshot(Base):
    """Pre-computed report snapshots for performance."""
    __tablename__ = "report_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Period info
    period_type = Column(SQLEnum(PeriodType), nullable=False, index=True)
    period_start = Column(Date, nullable=False, index=True)
    period_end = Column(Date, nullable=False, index=True)

    # Metrics (JSON structure)
    # Example: {
    #   "total_tickets": 150,
    #   "by_status": {"new": 20, "assigned": 50, "closed": 80},
    #   "by_priority": {"critical": 10, "high": 30, "medium": 60, "low": 50},
    #   "by_category": {"hardware": 40, "software": 30, ...},
    #   "avg_resolution_time_hours": 4.5,
    #   "sla_compliance_rate": 0.92,
    #   "tickets_breached": 12
    # }
    metrics = Column(JSON, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
