from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum, Text, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class WorkType(str, enum.Enum):
    DIAGNOSIS = "diagnosis"
    REPAIR = "repair"
    TESTING = "testing"
    COMMUNICATION = "communication"
    TRAVEL = "travel"
    WAITING = "waiting"
    OTHER = "other"


class Worklog(Base):
    __tablename__ = "worklogs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)

    # Content
    body = Column(Text, nullable=False)
    work_type = Column(SQLEnum(WorkType), nullable=False, default=WorkType.OTHER)

    # Time tracking (minutes)
    time_spent_minutes = Column(Integer)

    # Visibility
    is_internal = Column(String, default=False)  # Internal note, not visible to customer

    # Author
    author_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ticket = relationship("Ticket", back_populates="worklogs")
    author = relationship("User", back_populates="worklogs")
