from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
import boto3
from botocore.config import Config

from app.core.database import get_db
from app.core.config import settings
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.ticket import Ticket
from app.models.attachment import Attachment
from app.schemas.attachment import AttachmentCreate, AttachmentResponse, PresignedUrlResponse

router = APIRouter()


def get_s3_client():
    """Get S3 client."""
    return boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
        config=Config(signature_version='s3v4')
    )


@router.post("/presign", response_model=PresignedUrlResponse)
async def generate_presigned_url(
    file_name: str,
    mime_type: str,
    current_user: User = Depends(get_current_user)
):
    """Generate presigned URL for file upload."""
    import uuid
    from datetime import datetime

    # Generate unique storage key
    timestamp = datetime.utcnow().strftime('%Y%m%d')
    file_key = f"attachments/{current_user.tenant_id}/{timestamp}/{uuid.uuid4()}/{file_name}"

    # Generate presigned URL
    s3_client = get_s3_client()
    presigned_url = s3_client.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': settings.S3_BUCKET_NAME,
            'Key': file_key,
            'ContentType': mime_type
        },
        ExpiresIn=3600  # 1 hour
    )

    return {
        "upload_url": presigned_url,
        "storage_key": file_key
    }


@router.post("/tickets/{ticket_id}/attachments", response_model=AttachmentResponse, status_code=status.HTTP_201_CREATED)
async def create_attachment(
    ticket_id: str,
    attachment_data: AttachmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Register attachment metadata after upload."""
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

    # Create attachment record
    attachment = Attachment(
        tenant_id=current_user.tenant_id,
        ticket_id=ticket_id,
        created_by=current_user.id,
        **attachment_data.model_dump()
    )

    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    return attachment


@router.get("/tickets/{ticket_id}/attachments", response_model=List[AttachmentResponse])
async def list_attachments(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List attachments for ticket."""
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

    # Get attachments
    result = await db.execute(
        select(Attachment)
        .where(Attachment.ticket_id == ticket_id)
        .order_by(Attachment.created_at.desc())
    )
    attachments = result.scalars().all()

    return attachments
