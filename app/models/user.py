from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"  # System admin
    TENANT_ADMIN = "tenant_admin"  # Customer admin
    CALL_CENTER = "call_center"  # Call center agent
    AS_MANAGER = "as_manager"  # AS manager
    AS_ENGINEER = "as_engineer"  # Field engineer
    VIEWER = "viewer"  # Read-only


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Auth
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.VIEWER)

    # Profile
    full_name = Column(String, nullable=False)
    phone = Column(String)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    created_tickets = relationship("Ticket", back_populates="created_by_user", foreign_keys="Ticket.created_by")
    assigned_tickets = relationship("Assignment", back_populates="assignee_user", foreign_keys="Assignment.assignee_user_id")
    worklogs = relationship("Worklog", back_populates="author")
