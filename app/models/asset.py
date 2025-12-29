from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base


class Site(Base):
    __tablename__ = "sites"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Basic info
    name = Column(String, nullable=False, index=True)
    code = Column(String, unique=True, nullable=False, index=True)

    # Location
    address = Column(String)
    city = Column(String)
    state = Column(String)
    postal_code = Column(String)
    latitude = Column(String)
    longitude = Column(String)

    # Contact
    contact_name = Column(String)
    contact_phone = Column(String)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="sites")
    chargers = relationship("Charger", back_populates="site", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="site")


class Charger(Base):
    __tablename__ = "chargers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False, index=True)

    # Basic info
    name = Column(String, nullable=False)
    serial_number = Column(String, unique=True, nullable=False, index=True)

    # Hardware info
    vendor = Column(String)
    model = Column(String)
    firmware_version = Column(String)

    # CSMS info
    csms_charger_id = Column(String, unique=True, index=True)  # ID in CSMS system
    ocpp_protocol = Column(String)  # OCPP 1.6, 2.0.1, etc.

    # Capacity
    power_kw = Column(Integer)
    connector_count = Column(Integer)
    connector_types = Column(JSON)  # ["CCS", "CHAdeMO", etc.]

    # Status (synced from CSMS)
    current_status = Column(String)  # Available, Occupied, Faulted, etc.
    last_status_update = Column(DateTime)

    # Charger Metadata
    charger_metadata = Column(JSON)  # Flexible field for additional data

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    site = relationship("Site", back_populates="chargers")
    tickets = relationship("Ticket", back_populates="charger")
    csms_events = relationship("CsmsEventRef", back_populates="charger")
    firmware_jobs = relationship("FirmwareJobRef", back_populates="charger")
