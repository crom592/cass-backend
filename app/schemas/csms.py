from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any
from app.models.csms import FirmwareJobStatus


class ChargerStatusResponse(BaseModel):
    charger_id: str
    status: Optional[str]
    connector_status: List[Dict[str, Any]]
    last_heartbeat: Optional[datetime]
    last_update: datetime


class CsmsEventResponse(BaseModel):
    event_id: str
    event_type: str
    timestamp: datetime
    data: Dict[str, Any]


class FirmwareJobCreate(BaseModel):
    charger_id: str
    csms_job_id: str
    target_version: Optional[str] = None
    current_version: Optional[str] = None


class FirmwareJobResponse(BaseModel):
    id: str
    ticket_id: str
    charger_id: str
    csms_job_id: str
    target_version: Optional[str]
    current_version: Optional[str]
    last_status: FirmwareJobStatus
    status_message: Optional[str]
    requested_at: datetime
    last_checked_at: datetime
    completed_at: Optional[datetime]
    applied_version: Optional[str]

    class Config:
        from_attributes = True
