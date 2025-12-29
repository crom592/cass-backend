from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.models.assignment import AssigneeType


class AssignmentCreate(BaseModel):
    assignee_type: AssigneeType
    assignee_user_id: Optional[str] = None
    assignee_vendor_name: Optional[str] = None
    assignee_vendor_contact: Optional[str] = None
    due_at: Optional[datetime] = None
    notes: Optional[str] = None


class AssignmentResponse(BaseModel):
    id: str
    ticket_id: str
    assignee_type: AssigneeType
    assignee_user_id: Optional[str]
    assignee_vendor_name: Optional[str]
    assignee_vendor_contact: Optional[str]
    due_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    notes: Optional[str]
    assigned_by: str
    assigned_at: datetime

    class Config:
        from_attributes = True
