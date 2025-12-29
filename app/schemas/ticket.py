from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.models.ticket import TicketChannel, TicketCategory, TicketPriority, TicketStatus


class TicketCreate(BaseModel):
    site_id: str
    charger_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    channel: TicketChannel = TicketChannel.WEB
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.MEDIUM
    reporter_name: Optional[str] = None
    reporter_email: Optional[str] = None
    reporter_phone: Optional[str] = None


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[TicketCategory] = None
    priority: Optional[TicketPriority] = None
    reporter_name: Optional[str] = None
    reporter_email: Optional[str] = None
    reporter_phone: Optional[str] = None


class TicketStatusChange(BaseModel):
    to_status: TicketStatus
    reason: Optional[str] = None


class TicketResponse(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    charger_id: Optional[str]
    ticket_number: str
    title: str
    description: Optional[str]
    channel: TicketChannel
    category: TicketCategory
    priority: TicketPriority
    current_status: TicketStatus
    reporter_name: Optional[str]
    reporter_email: Optional[str]
    reporter_phone: Optional[str]
    opened_at: datetime
    closed_at: Optional[datetime]
    resolved_at: Optional[datetime]
    created_by: str
    created_at: datetime
    updated_at: datetime
    sla_breached: bool
    resolution_summary: Optional[str]

    class Config:
        from_attributes = True


class TicketStatusHistoryResponse(BaseModel):
    id: str
    ticket_id: str
    from_status: Optional[TicketStatus]
    to_status: TicketStatus
    reason: Optional[str]
    changed_by: str
    changed_at: datetime

    class Config:
        from_attributes = True
