from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class TicketChannel(str, enum.Enum):
    PHONE = "phone"
    EMAIL = "email"
    WEB = "web"
    MOBILE = "mobile"
    AUTO = "auto"  # Auto-created from CSMS event


class TicketCategory(str, enum.Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"
    POWER = "power"
    CONNECTOR = "connector"
    FIRMWARE = "firmware"
    OTHER = "other"


class TicketPriority(str, enum.Enum):
    CRITICAL = "critical"  # Service down
    HIGH = "high"  # Major functionality impacted
    MEDIUM = "medium"  # Minor issue
    LOW = "low"  # Cosmetic or enhancement


class TicketStatus(str, enum.Enum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    PENDING_CUSTOMER = "pending_customer"
    PENDING_VENDOR = "pending_vendor"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False, index=True)
    charger_id = Column(String, ForeignKey("chargers.id"), index=True)

    # Ticket info
    ticket_number = Column(String, unique=True, nullable=False, index=True)  # Human-readable ID
    title = Column(String, nullable=False)
    description = Column(Text)

    # Classification
    channel = Column(SQLEnum(TicketChannel), nullable=False, default=TicketChannel.WEB)
    category = Column(SQLEnum(TicketCategory), nullable=False, default=TicketCategory.OTHER)
    priority = Column(SQLEnum(TicketPriority), nullable=False, default=TicketPriority.MEDIUM)

    # Status
    current_status = Column(SQLEnum(TicketStatus), nullable=False, default=TicketStatus.NEW, index=True)

    # Reporter
    reporter_name = Column(String)
    reporter_email = Column(String)
    reporter_phone = Column(String)

    # Timestamps
    opened_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    closed_at = Column(DateTime, index=True)
    resolved_at = Column(DateTime)

    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # SLA tracking
    sla_breached = Column(Boolean, default=False, nullable=False, index=True)

    # Resolution
    resolution_summary = Column(Text)

    # Relationships
    tenant = relationship("Tenant", back_populates="tickets")
    site = relationship("Site", back_populates="tickets")
    charger = relationship("Charger", back_populates="tickets")
    created_by_user = relationship("User", back_populates="created_tickets", foreign_keys=[created_by])

    status_history = relationship("TicketStatusHistory", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketStatusHistory.changed_at")
    assignments = relationship("Assignment", back_populates="ticket", cascade="all, delete-orphan")
    worklogs = relationship("Worklog", back_populates="ticket", cascade="all, delete-orphan", order_by="Worklog.created_at")
    attachments = relationship("Attachment", back_populates="ticket", cascade="all, delete-orphan")
    csms_events = relationship("CsmsEventRef", back_populates="ticket")
    firmware_jobs = relationship("FirmwareJobRef", back_populates="ticket")
    sla_measurements = relationship("SlaMeasurement", back_populates="ticket", cascade="all, delete-orphan")


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)

    from_status = Column(SQLEnum(TicketStatus))
    to_status = Column(SQLEnum(TicketStatus), nullable=False)
    reason = Column(Text)  # Why the status changed

    changed_by = Column(String, ForeignKey("users.id"), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    ticket = relationship("Ticket", back_populates="status_history")
    changed_by_user = relationship("User")
