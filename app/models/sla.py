from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Enum as SQLEnum, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class SlaStatus(str, enum.Enum):
    ACTIVE = "active"
    MET = "met"
    BREACHED = "breached"
    CANCELLED = "cancelled"


class SlaPolicy(Base):
    """SLA policies for different ticket categories and priorities."""
    __tablename__ = "sla_policies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Policy criteria
    category = Column(String, nullable=False)  # TicketCategory enum value
    priority = Column(String, nullable=False)  # TicketPriority enum value

    # SLA targets (in minutes)
    response_time_minutes = Column(Integer, nullable=False)  # Time to first response
    resolution_time_minutes = Column(Integer, nullable=False)  # Time to resolve

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    measurements = relationship("SlaMeasurement", back_populates="policy")


class SlaMeasurement(Base):
    """SLA measurements for individual tickets."""
    __tablename__ = "sla_measurements"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    policy_id = Column(String, ForeignKey("sla_policies.id"), nullable=False)

    # Status
    status = Column(SQLEnum(SlaStatus), nullable=False, default=SlaStatus.ACTIVE, index=True)

    # Response SLA
    response_target_at = Column(DateTime, nullable=False)
    first_response_at = Column(DateTime)
    response_breached = Column(Boolean, default=False, nullable=False)

    # Resolution SLA
    resolution_target_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime)
    resolution_breached = Column(Boolean, default=False, nullable=False)

    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    breached_at = Column(DateTime)  # First breach time
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ticket = relationship("Ticket", back_populates="sla_measurements")
    policy = relationship("SlaPolicy", back_populates="measurements")
