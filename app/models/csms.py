from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class CsmsEventRef(Base):
    """Reference to CSMS events linked to tickets."""
    __tablename__ = "csms_event_refs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    charger_id = Column(String, ForeignKey("chargers.id"), nullable=False, index=True)

    # CSMS event info
    csms_event_id = Column(String, nullable=False, index=True)  # Event ID in CSMS
    event_type = Column(String)  # Fault, StatusNotification, etc.
    event_data = Column(JSON)  # Raw event data from CSMS

    occurred_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    ticket = relationship("Ticket", back_populates="csms_events")
    charger = relationship("Charger", back_populates="csms_events")


class FirmwareJobStatus(str, enum.Enum):
    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FirmwareJobRef(Base):
    """Reference to firmware update jobs in CSMS."""
    __tablename__ = "firmware_job_refs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    charger_id = Column(String, ForeignKey("chargers.id"), nullable=False, index=True)

    # CSMS job info
    csms_job_id = Column(String, nullable=False, index=True)  # Job ID in CSMS
    target_version = Column(String)
    current_version = Column(String)

    # Status
    last_status = Column(SQLEnum(FirmwareJobStatus), nullable=False, default=FirmwareJobStatus.REQUESTED)
    status_message = Column(String)

    # Timestamps
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)

    # Applied version (after successful update)
    applied_version = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ticket = relationship("Ticket", back_populates="firmware_jobs")
    charger = relationship("Charger", back_populates="firmware_jobs")
