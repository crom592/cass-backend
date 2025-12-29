from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from datetime import datetime
import httpx

from app.core.database import get_db
from app.core.config import settings
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.asset import Charger
from app.models.csms import CsmsEventRef, FirmwareJobRef
from app.schemas.csms import ChargerStatusResponse, CsmsEventResponse, FirmwareJobResponse, FirmwareJobCreate

router = APIRouter()


async def get_csms_client():
    """Get CSMS HTTP client."""
    return httpx.AsyncClient(
        base_url=settings.CSMS_API_BASE_URL,
        headers={"Authorization": f"Bearer {settings.CSMS_API_KEY}"}
    )


@router.get("/chargers/{charger_id}/status", response_model=ChargerStatusResponse)
async def get_charger_status(
    charger_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get charger status from CSMS."""
    # Verify charger exists
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

    # Get status from CSMS
    async with await get_csms_client() as client:
        try:
            response = await client.get(f"/chargers/{charger.csms_charger_id}/status")
            response.raise_for_status()
            csms_data = response.json()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"CSMS communication error: {str(e)}"
            )

    return {
        "charger_id": charger_id,
        "status": csms_data.get("status"),
        "connector_status": csms_data.get("connectors", []),
        "last_heartbeat": csms_data.get("last_heartbeat"),
        "last_update": datetime.utcnow()
    }


@router.get("/chargers/{charger_id}/events", response_model=List[CsmsEventResponse])
async def get_charger_events(
    charger_id: str,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get charger events from CSMS."""
    # Verify charger exists
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

    # Get events from CSMS
    async with await get_csms_client() as client:
        try:
            params = {}
            if from_date:
                params["from"] = from_date.isoformat()
            if to_date:
                params["to"] = to_date.isoformat()

            response = await client.get(
                f"/chargers/{charger.csms_charger_id}/events",
                params=params
            )
            response.raise_for_status()
            csms_events = response.json()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"CSMS communication error: {str(e)}"
            )

    return csms_events.get("events", [])


@router.post("/tickets/{ticket_id}/firmware-jobs", response_model=FirmwareJobResponse, status_code=status.HTTP_201_CREATED)
async def create_firmware_job_request(
    ticket_id: str,
    job_data: FirmwareJobCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create firmware update job reference (request object only)."""
    # This creates a reference to a firmware job that should be managed in CSMS
    # CASS only tracks the job status, not the actual firmware update process

    firmware_job = FirmwareJobRef(
        ticket_id=ticket_id,
        charger_id=job_data.charger_id,
        csms_job_id=job_data.csms_job_id,
        target_version=job_data.target_version,
        current_version=job_data.current_version
    )

    db.add(firmware_job)
    await db.commit()
    await db.refresh(firmware_job)

    return firmware_job
