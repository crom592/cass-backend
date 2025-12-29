from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any


class SiteResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    code: str
    address: Optional[str]
    city: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ChargerResponse(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    name: str
    serial_number: str
    vendor: Optional[str]
    model: Optional[str]
    firmware_version: Optional[str]
    current_status: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class ChargerDetail(ChargerResponse):
    csms_charger_id: Optional[str]
    ocpp_protocol: Optional[str]
    power_kw: Optional[int]
    connector_count: Optional[int]
    connector_types: Optional[List[str]]
    last_status_update: Optional[datetime]
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
