from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.ticket import Ticket
from app.models.assignment import Assignment
from app.schemas.assignment import AssignmentCreate, AssignmentResponse
from app.services.event_publisher import event_publisher

router = APIRouter()


@router.post("/tickets/{ticket_id}/assign", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
async def assign_ticket(
    ticket_id: str,
    assignment_data: AssignmentCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Assign ticket to user or vendor."""
    # Verify ticket exists
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

    # Create assignment
    assignment = Assignment(
        ticket_id=ticket_id,
        assigned_by=current_user.id,
        **assignment_data.model_dump()
    )

    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    # Publish SSE event for assignment
    background_tasks.add_task(
        event_publisher.publish_assignment,
        assignment,
        ticket,
        current_user.id
    )

    return assignment
