from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)

    # File metadata
    file_name = Column(String, nullable=False)
    mime_type = Column(String)
    file_size = Column(Integer)  # bytes

    # Storage info
    storage_key = Column(String, nullable=False)  # S3 key or path
    storage_url = Column(String)  # Full URL (if public)

    # Upload info
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    ticket = relationship("Ticket", back_populates="attachments")
    created_by_user = relationship("User")
