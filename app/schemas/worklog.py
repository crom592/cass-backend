from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.models.worklog import WorkType


class WorklogCreate(BaseModel):
    body: str
    work_type: WorkType = WorkType.OTHER
    time_spent_minutes: Optional[int] = None
    is_internal: bool = False


class WorklogResponse(BaseModel):
    id: str
    ticket_id: str
    body: str
    work_type: WorkType
    time_spent_minutes: Optional[int]
    is_internal: bool
    author_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
