"""
SLA Schemas Module

Pydantic schemas for SLA-related API requests and responses.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.models.sla import SlaStatus


# ============================================================================
# SLA Policy Schemas
# ============================================================================

class SlaPolicyCreate(BaseModel):
    """Schema for creating a new SLA policy."""
    category: str = Field(..., description="Ticket category (e.g., hardware, software)")
    priority: str = Field(..., description="Ticket priority (e.g., critical, high, medium, low)")
    response_time_minutes: int = Field(..., gt=0, description="Target response time in minutes")
    resolution_time_minutes: int = Field(..., gt=0, description="Target resolution time in minutes")


class SlaPolicyUpdate(BaseModel):
    """Schema for updating an SLA policy."""
    response_time_minutes: Optional[int] = Field(None, gt=0, description="Target response time in minutes")
    resolution_time_minutes: Optional[int] = Field(None, gt=0, description="Target resolution time in minutes")
    is_active: Optional[bool] = Field(None, description="Whether the policy is active")


class SlaPolicyResponse(BaseModel):
    """Schema for SLA policy response."""
    id: str
    tenant_id: str
    category: str
    priority: str
    response_time_minutes: int
    resolution_time_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# SLA Measurement Schemas
# ============================================================================

class SlaMeasurementResponse(BaseModel):
    """Schema for SLA measurement response."""
    id: str
    ticket_id: str
    policy_id: str
    status: SlaStatus
    response_target_at: datetime
    first_response_at: Optional[datetime]
    response_breached: bool
    resolution_target_at: datetime
    resolved_at: Optional[datetime]
    resolution_breached: bool
    started_at: datetime
    breached_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# SLA Status Schemas
# ============================================================================

class SlaCalculationDetails(BaseModel):
    """Detailed SLA calculation results."""
    ticket_id: str
    policy_id: Optional[str]
    response_target_minutes: Optional[int]
    resolution_target_minutes: Optional[int]
    response_target_at: Optional[datetime]
    resolution_target_at: Optional[datetime]
    first_response_at: Optional[datetime]
    actual_response_minutes: Optional[float]
    actual_resolution_minutes: Optional[float]
    response_breached: bool
    resolution_breached: bool
    overall_status: SlaStatus


class SlaPolicyInfo(BaseModel):
    """Brief SLA policy information."""
    id: str
    response_time_minutes: int
    resolution_time_minutes: int


class SlaMeasurementInfo(BaseModel):
    """Brief SLA measurement information."""
    id: str
    status: str
    response_target_at: Optional[str]
    resolution_target_at: Optional[str]
    first_response_at: Optional[str]
    resolved_at: Optional[str]
    response_breached: bool
    resolution_breached: bool
    breached_at: Optional[str]


class SlaTicketStatusResponse(BaseModel):
    """Complete SLA status for a ticket."""
    ticket_id: str
    ticket_number: str
    current_status: str
    priority: str
    category: str
    opened_at: Optional[str]
    resolved_at: Optional[str]
    sla_breached: bool
    policy: Optional[SlaPolicyInfo]
    measurement: Optional[SlaMeasurementInfo]
    calculation: dict


class SlaBreachStatusResponse(BaseModel):
    """SLA breach status for a ticket."""
    ticket_id: str
    is_breached: bool
    response_breached: bool
    resolution_breached: bool
    breach_type: Optional[str] = Field(None, description="Type of breach: response, resolution, or both")
    time_to_response_breach_minutes: Optional[float] = Field(None, description="Minutes until response breach (negative if already breached)")
    time_to_resolution_breach_minutes: Optional[float] = Field(None, description="Minutes until resolution breach (negative if already breached)")
    overall_status: Optional[SlaStatus]


# ============================================================================
# Batch Job Schemas
# ============================================================================

class SlaRecalculationRequest(BaseModel):
    """Request schema for manual SLA recalculation."""
    ticket_ids: Optional[List[str]] = Field(None, description="Specific ticket IDs to recalculate. If empty, recalculates all open tickets.")


class SlaBatchResultResponse(BaseModel):
    """Result of SLA batch processing."""
    total_processed: int
    breached: int
    within_sla: int
    errors: List[str]
    processed_at: str
    started_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class SlaSchedulerStatusResponse(BaseModel):
    """Status of the SLA scheduler."""
    running: bool
    interval_seconds: int
    last_run: Optional[str]
    run_count: int
    error_count: int
    next_run_in_seconds: Optional[int]


# ============================================================================
# List Response Schemas
# ============================================================================

class SlaPolicyListResponse(BaseModel):
    """List of SLA policies."""
    policies: List[SlaPolicyResponse]
    total: int


class SlaMeasurementListResponse(BaseModel):
    """List of SLA measurements."""
    measurements: List[SlaMeasurementResponse]
    total: int


# ============================================================================
# Statistics Schemas
# ============================================================================

class SlaStatisticsResponse(BaseModel):
    """SLA statistics summary."""
    total_tickets: int
    tickets_with_sla: int
    breached_count: int
    met_count: int
    active_count: int
    cancelled_count: int
    average_response_time_minutes: Optional[float]
    average_resolution_time_minutes: Optional[float]
    breach_rate_percentage: float
    period_start: Optional[datetime]
    period_end: Optional[datetime]
