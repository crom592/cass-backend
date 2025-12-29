from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List, Optional
from datetime import datetime
import uuid
import logging

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.ticket import Ticket, TicketStatusHistory, TicketStatus
from app.schemas.ticket import (
    TicketCreate,
    TicketUpdate,
    TicketStatusChange,
    TicketResponse,
    TicketStatusHistoryResponse
)
from app.schemas.sla import SlaTicketStatusResponse
from app.services.sla_service import SlaService
from app.services.event_publisher import event_publisher


logger = logging.getLogger(__name__)

router = APIRouter()


def generate_ticket_number() -> str:
    """Generate unique ticket number."""
    return f"TKT-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    ticket_data: TicketCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new ticket."""
    ticket = Ticket(
        tenant_id=current_user.tenant_id,
        ticket_number=generate_ticket_number(),
        created_by=current_user.id,
        **ticket_data.model_dump()
    )

    db.add(ticket)

    # Create initial status history
    status_history = TicketStatusHistory(
        ticket_id=ticket.id,
        from_status=None,
        to_status=TicketStatus.NEW,
        reason="Ticket created",
        changed_by=current_user.id
    )
    db.add(status_history)

    await db.commit()
    await db.refresh(ticket)

    # Initialize SLA measurement for the new ticket
    try:
        sla_service = SlaService(db)
        await sla_service.initialize_sla_for_new_ticket(ticket)
    except Exception as e:
        logger.warning(f"Failed to initialize SLA for ticket {ticket.id}: {e}")

    # Publish SSE event for ticket creation
    background_tasks.add_task(
        event_publisher.publish_ticket_created,
        ticket,
        current_user.id
    )

    return ticket


@router.get("", response_model=List[TicketResponse])
async def list_tickets(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    site_id: Optional[str] = Query(None),
    charger_id: Optional[str] = Query(None),
    sla_breached: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List tickets with filters."""
    query = select(Ticket).where(Ticket.tenant_id == current_user.tenant_id)

    # Apply filters
    if status:
        query = query.where(Ticket.current_status == status)
    if priority:
        query = query.where(Ticket.priority == priority)
    if category:
        query = query.where(Ticket.category == category)
    if site_id:
        query = query.where(Ticket.site_id == site_id)
    if charger_id:
        query = query.where(Ticket.charger_id == charger_id)
    if sla_breached is not None:
        query = query.where(Ticket.sla_breached == sla_breached)

    # Order by created date descending
    query = query.order_by(Ticket.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    tickets = result.scalars().all()

    return tickets


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get ticket by ID."""
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

    return ticket


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: str,
    ticket_update: TicketUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update ticket details."""
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

    # Update fields
    update_data = ticket_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ticket, field, value)

    await db.commit()
    await db.refresh(ticket)

    # Publish SSE event for ticket update
    background_tasks.add_task(
        event_publisher.publish_ticket_updated,
        ticket,
        update_data,
        current_user.id
    )

    return ticket


@router.post("/{ticket_id}/status", response_model=TicketResponse)
async def change_ticket_status(
    ticket_id: str,
    status_change: TicketStatusChange,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change ticket status."""
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

    # Store old status
    old_status = ticket.current_status

    # Update status
    ticket.current_status = status_change.to_status

    # Update timestamps based on status
    if status_change.to_status == TicketStatus.RESOLVED:
        ticket.resolved_at = datetime.utcnow()
    elif status_change.to_status == TicketStatus.CLOSED:
        ticket.closed_at = datetime.utcnow()

    # Create status history
    status_history = TicketStatusHistory(
        ticket_id=ticket.id,
        from_status=old_status,
        to_status=status_change.to_status,
        reason=status_change.reason,
        changed_by=current_user.id
    )
    db.add(status_history)

    await db.commit()
    await db.refresh(ticket)

    # Update SLA measurements after status change
    try:
        sla_service = SlaService(db)
        await sla_service.update_sla_measurements(ticket_id)
    except Exception as e:
        logger.warning(f"Failed to update SLA for ticket {ticket_id}: {e}")

    # Publish SSE event for status change
    background_tasks.add_task(
        event_publisher.publish_ticket_status_changed,
        ticket,
        old_status,
        status_change.to_status,
        current_user.id,
        status_change.reason
    )

    return ticket


@router.get("/{ticket_id}/history", response_model=List[TicketStatusHistoryResponse])
async def get_ticket_status_history(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get ticket status change history."""
    # Verify ticket exists and belongs to user's tenant
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

    # Get status history
    result = await db.execute(
        select(TicketStatusHistory)
        .where(TicketStatusHistory.ticket_id == ticket_id)
        .order_by(TicketStatusHistory.changed_at.desc())
    )
    history = result.scalars().all()

    return history


@router.get("/{ticket_id}/sla", response_model=SlaTicketStatusResponse)
async def get_ticket_sla(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get SLA status for a specific ticket.

    Returns comprehensive SLA information including policy, measurements, and current calculations.
    """
    # Verify ticket exists and belongs to user's tenant
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
