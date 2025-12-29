from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.ticket import Ticket
from app.models.worklog import Worklog
from app.schemas.worklog import WorklogCreate, WorklogResponse
from app.services.event_publisher import event_publisher

router = APIRouter()


@router.post("/tickets/{ticket_id}/worklogs", response_model=WorklogResponse, status_code=status.HTTP_201_CREATED)
async def create_worklog(
    ticket_id: str,
    worklog_data: WorklogCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create worklog entry for ticket."""
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

    # Create worklog
    worklog = Worklog(
        ticket_id=ticket_id,
        author_id=current_user.id,
        **worklog_data.model_dump()
    )

    db.add(worklog)
    await db.commit()
    await db.refresh(worklog)

    # Publish SSE event for worklog creation
    background_tasks.add_task(
        event_publisher.publish_worklog,
        worklog,
        ticket,
        current_user.id
    )

    return worklog


@router.get("/tickets/{ticket_id}/worklogs", response_model=List[WorklogResponse])
async def list_worklogs(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List worklogs for ticket."""
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

    # Get worklogs
    result = await db.execute(
        select(Worklog)
        .where(Worklog.ticket_id == ticket_id)
        .order_by(Worklog.created_at.desc())
    )
    worklogs = result.scalars().all()

    return worklogs
