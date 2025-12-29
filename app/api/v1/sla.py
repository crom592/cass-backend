"""
SLA API Endpoints

Provides REST API endpoints for SLA policy management, measurements, and recalculation.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional
from datetime import datetime
import logging

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.ticket import Ticket
from app.models.sla import SlaPolicy, SlaMeasurement, SlaStatus
from app.services.sla_service import SlaService
from app.jobs.sla_batch import (
    trigger_sla_recalculation,
    get_sla_scheduler,
    process_single_ticket_sla
)
from app.schemas.sla import (
    SlaPolicyCreate,
    SlaPolicyUpdate,
    SlaPolicyResponse,
    SlaPolicyListResponse,
    SlaMeasurementResponse,
    SlaTicketStatusResponse,
    SlaBreachStatusResponse,
    SlaRecalculationRequest,
    SlaBatchResultResponse,
    SlaSchedulerStatusResponse,
    SlaStatisticsResponse
)


logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# SLA Policy Endpoints
# ============================================================================

@router.get("/policies", response_model=SlaPolicyListResponse)
async def list_sla_policies(
    active_only: bool = Query(True, description="Only return active policies"),
    category: Optional[str] = Query(None, description="Filter by category"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all SLA policies for the current tenant.

    Returns a list of SLA policies with optional filtering by status, category, or priority.
    """
    query = select(SlaPolicy).where(SlaPolicy.tenant_id == current_user.tenant_id)

    if active_only:
        query = query.where(SlaPolicy.is_active == True)

    if category:
        query = query.where(SlaPolicy.category == category)

    if priority:
        query = query.where(SlaPolicy.priority == priority)

    query = query.order_by(SlaPolicy.priority, SlaPolicy.category)

    result = await db.execute(query)
    policies = result.scalars().all()

    return SlaPolicyListResponse(
        policies=policies,
        total=len(policies)
    )


@router.post("/policies", response_model=SlaPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_sla_policy(
    policy_data: SlaPolicyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new SLA policy.

    Creates a policy for a specific category/priority combination.
    Only one active policy should exist per category/priority pair.
    """
    # Check if policy already exists for this category/priority
    existing = await db.execute(
        select(SlaPolicy).where(
            and_(
                SlaPolicy.tenant_id == current_user.tenant_id,
                SlaPolicy.category == policy_data.category,
                SlaPolicy.priority == policy_data.priority,
                SlaPolicy.is_active == True
            )
        )
    )

    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Active SLA policy already exists for category '{policy_data.category}' and priority '{policy_data.priority}'"
        )

    sla_service = SlaService(db)
    policy = await sla_service.create_policy(
        tenant_id=current_user.tenant_id,
        category=policy_data.category,
        priority=policy_data.priority,
        response_time_minutes=policy_data.response_time_minutes,
        resolution_time_minutes=policy_data.resolution_time_minutes
    )

    return policy


@router.get("/policies/{policy_id}", response_model=SlaPolicyResponse)
async def get_sla_policy(
    policy_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific SLA policy by ID.
    """
    result = await db.execute(
        select(SlaPolicy).where(
            and_(
                SlaPolicy.id == policy_id,
                SlaPolicy.tenant_id == current_user.tenant_id
            )
        )
    )
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLA policy not found"
        )

    return policy


@router.patch("/policies/{policy_id}", response_model=SlaPolicyResponse)
async def update_sla_policy(
    policy_id: str,
    policy_update: SlaPolicyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an SLA policy.

    Only response_time_minutes, resolution_time_minutes, and is_active can be updated.
    """
    result = await db.execute(
        select(SlaPolicy).where(
            and_(
                SlaPolicy.id == policy_id,
                SlaPolicy.tenant_id == current_user.tenant_id
            )
        )
    )
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLA policy not found"
        )

    sla_service = SlaService(db)
    updated_policy = await sla_service.update_policy(
        policy_id=policy_id,
        **policy_update.model_dump(exclude_unset=True)
    )

    return updated_policy


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_sla_policy(
    policy_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Deactivate an SLA policy.

    This soft-deletes the policy by setting is_active to False.
    Existing measurements remain unaffected.
    """
    result = await db.execute(
        select(SlaPolicy).where(
            and_(
                SlaPolicy.id == policy_id,
                SlaPolicy.tenant_id == current_user.tenant_id
            )
        )
    )
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLA policy not found"
        )

    policy.is_active = False
    await db.commit()


# ============================================================================
# Ticket SLA Status Endpoints
# ============================================================================

@router.get("/tickets/{ticket_id}", response_model=SlaTicketStatusResponse)
async def get_ticket_sla_status(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get complete SLA status for a specific ticket.

    Returns policy information, measurements, and current calculation results.
    """
    # Verify ticket exists and belongs to tenant
    result = await db.execute(
        select(Ticket).where(
            and_(
                Ticket.id == ticket_id,
                Ticket.tenant_id == current_user.tenant_id
            )
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )

    sla_service = SlaService(db)

    try:
        sla_status = await sla_service.get_sla_status_for_ticket(ticket_id)
        return sla_status
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/tickets/{ticket_id}/breach", response_model=SlaBreachStatusResponse)
async def check_ticket_sla_breach(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Check if SLA is breached for a specific ticket.

    Returns breach status and time remaining until breach (if not yet breached).
    """
    # Verify ticket exists and belongs to tenant
    result = await db.execute(
        select(Ticket).where(
            and_(
                Ticket.id == ticket_id,
                Ticket.tenant_id == current_user.tenant_id
            )
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )

    sla_service = SlaService(db)

    try:
        breach_status = await sla_service.check_sla_breach(ticket_id)
        return breach_status
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/tickets/{ticket_id}/recalculate", response_model=SlaTicketStatusResponse)
async def recalculate_ticket_sla(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually recalculate SLA for a specific ticket.

    Updates the SLA measurement record with current calculation.
    """
    # Verify ticket exists and belongs to tenant
    result = await db.execute(
        select(Ticket).where(
            and_(
                Ticket.id == ticket_id,
                Ticket.tenant_id == current_user.tenant_id
            )
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )

    sla_service = SlaService(db)

    try:
        await sla_service.update_sla_measurements(ticket_id)
        sla_status = await sla_service.get_sla_status_for_ticket(ticket_id)
        return sla_status
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


# ============================================================================
# Batch Recalculation Endpoints
# ============================================================================

@router.post("/recalculate", response_model=SlaBatchResultResponse)
async def trigger_sla_batch_recalculation(
    request: Optional[SlaRecalculationRequest] = None,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger manual SLA recalculation for all open tickets.

    If ticket_ids is provided in the request, only those tickets are recalculated.
    Otherwise, all open tickets in the tenant are processed.
    """
    if request and request.ticket_ids:
        # Process specific tickets
        sla_service = SlaService(db)
        total_processed = 0
        breached = 0
        within_sla = 0
        errors = []

        for ticket_id in request.ticket_ids:
            try:
                # Verify ticket belongs to tenant
                result = await db.execute(
                    select(Ticket).where(
                        and_(
                            Ticket.id == ticket_id,
                            Ticket.tenant_id == current_user.tenant_id
                        )
                    )
                )
                ticket = result.scalar_one_or_none()

                if not ticket:
                    errors.append(f"Ticket not found: {ticket_id}")
                    continue

                measurement = await sla_service.update_sla_measurements(ticket_id)
                total_processed += 1

                if measurement and (measurement.response_breached or measurement.resolution_breached):
                    breached += 1
                else:
                    within_sla += 1

            except Exception as e:
                errors.append(f"Error processing {ticket_id}: {str(e)}")

        return SlaBatchResultResponse(
            total_processed=total_processed,
            breached=breached,
            within_sla=within_sla,
            errors=errors,
            processed_at=datetime.utcnow().isoformat()
        )
    else:
        # Process all open tickets
        result = await trigger_sla_recalculation()
        return SlaBatchResultResponse(**result)


@router.get("/scheduler/status", response_model=SlaSchedulerStatusResponse)
async def get_scheduler_status(
    current_user: User = Depends(get_current_user)
):
    """
    Get the current status of the SLA batch scheduler.

    Returns information about the scheduler including run count and next scheduled run.
    """
    scheduler = get_sla_scheduler()
    status_info = scheduler.get_status()
    return SlaSchedulerStatusResponse(**status_info)


# ============================================================================
# Statistics Endpoints
# ============================================================================

@router.get("/statistics", response_model=SlaStatisticsResponse)
async def get_sla_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to include in statistics"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get SLA statistics for the current tenant.

    Returns aggregate metrics including breach rates and average times.
    """
    from datetime import timedelta

    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)

    # Get total tickets in period
    total_result = await db.execute(
        select(func.count(Ticket.id)).where(
            and_(
                Ticket.tenant_id == current_user.tenant_id,
                Ticket.opened_at >= period_start,
                Ticket.opened_at <= period_end
            )
        )
    )
    total_tickets = total_result.scalar() or 0

    # Get tickets with SLA measurements
    sla_result = await db.execute(
        select(func.count(SlaMeasurement.id)).join(Ticket).where(
            and_(
                Ticket.tenant_id == current_user.tenant_id,
                Ticket.opened_at >= period_start,
                Ticket.opened_at <= period_end
            )
        )
    )
    tickets_with_sla = sla_result.scalar() or 0

    # Count by status
    status_counts = {}
    for sla_status in SlaStatus:
        count_result = await db.execute(
            select(func.count(SlaMeasurement.id)).join(Ticket).where(
                and_(
                    Ticket.tenant_id == current_user.tenant_id,
                    Ticket.opened_at >= period_start,
                    Ticket.opened_at <= period_end,
                    SlaMeasurement.status == sla_status
                )
            )
        )
        status_counts[sla_status.value] = count_result.scalar() or 0

    # Calculate breach rate
    breach_rate = 0.0
    if tickets_with_sla > 0:
        breach_rate = (status_counts.get("breached", 0) / tickets_with_sla) * 100

    # TODO: Calculate average response and resolution times
    # This would require more complex aggregation queries

    return SlaStatisticsResponse(
        total_tickets=total_tickets,
        tickets_with_sla=tickets_with_sla,
        breached_count=status_counts.get("breached", 0),
        met_count=status_counts.get("met", 0),
        active_count=status_counts.get("active", 0),
        cancelled_count=status_counts.get("cancelled", 0),
        average_response_time_minutes=None,  # TODO: Implement
        average_resolution_time_minutes=None,  # TODO: Implement
        breach_rate_percentage=round(breach_rate, 2),
        period_start=period_start,
        period_end=period_end
    )


# ============================================================================
# Measurement List Endpoint
# ============================================================================

@router.get("/measurements", response_model=List[SlaMeasurementResponse])
async def list_sla_measurements(
    status_filter: Optional[SlaStatus] = Query(None, alias="status", description="Filter by SLA status"),
    response_breached: Optional[bool] = Query(None, description="Filter by response breach status"),
    resolution_breached: Optional[bool] = Query(None, description="Filter by resolution breach status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List SLA measurements for tickets in the current tenant.

    Supports filtering by status and breach conditions.
    """
    query = (
        select(SlaMeasurement)
        .join(Ticket)
        .where(Ticket.tenant_id == current_user.tenant_id)
    )

    if status_filter:
        query = query.where(SlaMeasurement.status == status_filter)

    if response_breached is not None:
        query = query.where(SlaMeasurement.response_breached == response_breached)

    if resolution_breached is not None:
        query = query.where(SlaMeasurement.resolution_breached == resolution_breached)

    query = query.order_by(SlaMeasurement.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    measurements = result.scalars().all()

    return measurements
