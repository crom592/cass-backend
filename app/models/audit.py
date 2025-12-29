from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text
from datetime import datetime
import uuid
from app.core.database import Base


class AuditLog(Base):
    """Immutable audit trail for all important actions."""
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Actor
    actor_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    actor_email = Column(String)  # Snapshot for historical record

    # Entity
    entity_type = Column(String, nullable=False, index=True)  # "ticket", "user", "assignment", etc.
    entity_id = Column(String, nullable=False, index=True)

    # Action
    action = Column(String, nullable=False, index=True)  # "create", "update", "delete", "status_change", etc.
    description = Column(Text)  # Human-readable description

    # Changes (JSON diff)
    # Example: {"status": {"old": "new", "new": "assigned"}, "priority": {"old": "low", "new": "high"}}
    changes = Column(JSON)

    # Metadata
    ip_address = Column(String)
    user_agent = Column(String)

    # Timestamp (immutable)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
