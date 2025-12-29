"""Webhook schemas for CSMS integration."""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class WebhookEventType(str, Enum):
    """Types of webhook events from CSMS."""
    # Charger events
    STATUS_NOTIFICATION = "StatusNotification"
    FAULT = "Fault"
    HEARTBEAT = "Heartbeat"
    BOOT_NOTIFICATION = "BootNotification"
    DIAGNOSTIC = "Diagnostic"

    # Firmware events
    FIRMWARE_STATUS = "FirmwareStatus"
    FIRMWARE_DOWNLOAD_STARTED = "FirmwareDownloadStarted"
    FIRMWARE_DOWNLOAD_COMPLETED = "FirmwareDownloadCompleted"
    FIRMWARE_INSTALL_STARTED = "FirmwareInstallStarted"
    FIRMWARE_INSTALL_COMPLETED = "FirmwareInstallCompleted"
    FIRMWARE_INSTALL_FAILED = "FirmwareInstallFailed"

    # Transaction events
    TRANSACTION_START = "TransactionStart"
    TRANSACTION_END = "TransactionEnd"

    # General
    GENERIC = "Generic"


class ChargerEventSeverity(str, Enum):
    """Severity levels for charger events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class FirmwareUpdateStatus(str, Enum):
    """Status values for firmware updates."""
    SCHEDULED = "scheduled"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Base webhook payload
class CSMSWebhookPayload(BaseModel):
    """Base webhook payload from CSMS."""
    event_id: str = Field(..., description="Unique event ID from CSMS")
    event_type: WebhookEventType = Field(..., description="Type of webhook event")
    timestamp: datetime = Field(..., description="When the event occurred in CSMS")
    csms_charger_id: str = Field(..., description="Charger ID in CSMS system")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific payload data")

    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "evt_123456789",
                "event_type": "StatusNotification",
                "timestamp": "2024-01-15T10:30:00Z",
                "csms_charger_id": "CP001",
                "data": {
                    "status": "Available",
                    "connector_id": 1
                }
            }
        }


# Charger event webhook payload
class ChargerEventPayload(BaseModel):
    """Webhook payload for charger events."""
    event_id: str = Field(..., description="Unique event ID from CSMS")
    event_type: WebhookEventType = Field(..., description="Type of charger event")
    timestamp: datetime = Field(..., description="When the event occurred")
    csms_charger_id: str = Field(..., description="Charger ID in CSMS system")

    # Event details
    severity: ChargerEventSeverity = Field(default=ChargerEventSeverity.INFO, description="Event severity level")
    connector_id: Optional[int] = Field(None, description="Connector ID if event is connector-specific")
    status: Optional[str] = Field(None, description="Current status")
    error_code: Optional[str] = Field(None, description="Error code if applicable")
    vendor_error_code: Optional[str] = Field(None, description="Vendor-specific error code")
    info: Optional[str] = Field(None, description="Additional information about the event")

    # Fault-specific fields
    fault_type: Optional[str] = Field(None, description="Type of fault (if Fault event)")
    fault_description: Optional[str] = Field(None, description="Fault description")

    # Additional data
    data: Dict[str, Any] = Field(default_factory=dict, description="Additional event data")

    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "evt_fault_123",
                "event_type": "Fault",
                "timestamp": "2024-01-15T10:30:00Z",
                "csms_charger_id": "CP001",
                "severity": "critical",
                "connector_id": 1,
                "status": "Faulted",
                "error_code": "GroundFailure",
                "vendor_error_code": "E001",
                "info": "Ground fault detected on connector 1",
                "fault_type": "Hardware",
                "fault_description": "Ground fault protection triggered"
            }
        }


# Firmware update webhook payload
class FirmwareUpdatePayload(BaseModel):
    """Webhook payload for firmware update status."""
    event_id: str = Field(..., description="Unique event ID from CSMS")
    timestamp: datetime = Field(..., description="When the status changed")
    csms_charger_id: str = Field(..., description="Charger ID in CSMS system")
    csms_job_id: str = Field(..., description="Firmware job ID in CSMS")

    # Status
    status: FirmwareUpdateStatus = Field(..., description="Current firmware update status")
    status_message: Optional[str] = Field(None, description="Detailed status message")

    # Version info
    current_version: Optional[str] = Field(None, description="Current firmware version")
    target_version: Optional[str] = Field(None, description="Target firmware version")
    applied_version: Optional[str] = Field(None, description="Actually applied version (after successful update)")

    # Progress
    progress_percent: Optional[int] = Field(None, ge=0, le=100, description="Download/install progress")

    # Error info (for failed updates)
    error_code: Optional[str] = Field(None, description="Error code if update failed")
    error_message: Optional[str] = Field(None, description="Error message if update failed")

    # Additional data
    data: Dict[str, Any] = Field(default_factory=dict, description="Additional firmware update data")

    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "evt_fw_456",
                "timestamp": "2024-01-15T10:30:00Z",
                "csms_charger_id": "CP001",
                "csms_job_id": "fwjob_789",
                "status": "installed",
                "status_message": "Firmware update completed successfully",
                "current_version": "1.2.3",
                "target_version": "1.3.0",
                "applied_version": "1.3.0",
                "progress_percent": 100
            }
        }


# Response schemas
class WebhookResponse(BaseModel):
    """Standard webhook response."""
    success: bool = Field(..., description="Whether the webhook was processed successfully")
    message: str = Field(..., description="Response message")
    event_id: Optional[str] = Field(None, description="ID of the processed event")
    internal_ref_id: Optional[str] = Field(None, description="Internal reference ID if event was stored")
    ticket_id: Optional[str] = Field(None, description="Ticket ID if a ticket was created/updated")


class WebhookErrorResponse(BaseModel):
    """Webhook error response."""
    success: bool = Field(default=False)
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


# Batch webhook payload (for bulk events)
class BatchWebhookPayload(BaseModel):
    """Batch webhook payload for multiple events."""
    batch_id: str = Field(..., description="Unique batch ID")
    events: List[CSMSWebhookPayload] = Field(..., min_length=1, max_length=100)

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "batch_123",
                "events": [
                    {
                        "event_id": "evt_1",
                        "event_type": "StatusNotification",
                        "timestamp": "2024-01-15T10:30:00Z",
                        "csms_charger_id": "CP001",
                        "data": {"status": "Available"}
                    }
                ]
            }
        }


class BatchWebhookResponse(BaseModel):
    """Response for batch webhook processing."""
    success: bool
    batch_id: str
    total_events: int
    processed_events: int
    failed_events: int
    results: List[WebhookResponse] = Field(default_factory=list)
    errors: List[WebhookErrorResponse] = Field(default_factory=list)
