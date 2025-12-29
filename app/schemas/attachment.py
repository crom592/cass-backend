from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class PresignedUrlResponse(BaseModel):
    upload_url: str
    storage_key: str


class AttachmentCreate(BaseModel):
    file_name: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    storage_key: str
    storage_url: Optional[str] = None


class AttachmentResponse(BaseModel):
    id: str
    tenant_id: str
    ticket_id: str
    file_name: str
    mime_type: Optional[str]
    file_size: Optional[int]
    storage_key: str
    storage_url: Optional[str]
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True
