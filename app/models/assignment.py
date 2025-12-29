from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class AssigneeType(str, enum.Enum):
    USER = "user"  # Internal user (AS engineer)
    VENDOR = "vendor"  # External vendor


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)

    # Assignee
    assignee_type = Column(SQLEnum(AssigneeType), nullable=False)
    assignee_user_id = Column(String, ForeignKey("users.id"), index=True)  # If type=USER
    assignee_vendor_name = Column(String)  # If type=VENDOR
    assignee_vendor_contact = Column(String)

    # Schedule
    due_at = Column(DateTime, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Notes
    notes = Column(Text)

    # Assignment metadata
    assigned_by = Column(String, ForeignKey("users.id"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    ticket = relationship("Ticket", back_populates="assignments")
    assignee_user = relationship("User", back_populates="assigned_tickets", foreign_keys=[assignee_user_id])
    assigned_by_user = relationship("User", foreign_keys=[assigned_by])
