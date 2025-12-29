from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.asset import Site, Charger
from app.schemas.asset import SiteResponse, ChargerResponse, ChargerDetail

router = APIRouter()


@router.get("/sites", response_model=List[SiteResponse])
async def list_sites(
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List sites."""
    query = select(Site).where(Site.tenant_id == current_user.tenant_id)

    if is_active is not None:
        query = query.where(Site.is_active == is_active)

    query = query.order_by(Site.name).offset(skip).limit(limit)

    result = await db.execute(query)
    sites = result.scalars().all()

    return sites


@router.get("/chargers", response_model=List[ChargerResponse])
async def list_chargers(
    site_id: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List chargers."""
    query = select(Charger).where(Charger.tenant_id == current_user.tenant_id)

    if site_id:
        query = query.where(Charger.site_id == site_id)
    if is_active is not None:
        query = query.where(Charger.is_active == is_active)

    query = query.order_by(Charger.name).offset(skip).limit(limit)

    result = await db.execute(query)
    chargers = result.scalars().all()

    return chargers


@router.get("/chargers/{charger_id}", response_model=ChargerDetail)
async def get_charger(
    charger_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get charger details."""
    result = await db.execute(
        select(Charger).where(
            and_(
                Charger.id == charger_id,
                Charger.tenant_id == current_user.tenant_id
            )
        )
    )
    charger = result.scalar_one_or_none()

    if not charger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Charger not found"
        )

    return charger
