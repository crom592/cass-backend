"""Webhook endpoints for CSMS integration."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.webhook import (
    BatchWebhookPayload,
    BatchWebhookResponse,
    ChargerEventPayload,
    CSMSWebhookPayload,
    FirmwareUpdatePayload,
    WebhookErrorResponse,
    WebhookResponse,
)
from app.services.webhook_service import WebhookService, get_webhook_service


logger = logging.getLogger(__name__)

router = APIRouter()


async def verify_csms_signature(
    request: Request,
    x_csms_signature: Optional[str] = Header(None, alias="X-CSMS-Signature"),
    x_csms_timestamp: Optional[str] = Header(None, alias="X-CSMS-Timestamp"),
) -> bytes:
    """
    Dependency to verify CSMS webhook signature.

    Args:
        request: The incoming request
        x_csms_signature: The signature header from CSMS
        x_csms_timestamp: The timestamp header from CSMS

    Returns:
        The raw request body bytes

    Raises:
        HTTPException: If signature verification fails
    """
    # Read the raw body
    body = await request.body()

    # Skip verification if no signature provided (for development)
    if not x_csms_signature:
        logger.warning("No signature header provided, skipping verification")
        return body

    # Verify signature
    if not WebhookService.verify_signature(body, x_csms_signature, x_csms_timestamp):
        logger.error("Invalid webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )

    return body


@router.post(
    "/csms",
    response_model=WebhookResponse,
    responses={
        401: {"model": WebhookErrorResponse, "description": "Invalid signature"},
        422: {"model": WebhookErrorResponse, "description": "Invalid payload"},
        500: {"model": WebhookErrorResponse, "description": "Internal server error"},
    },
    summary="CSMS Webhook Receiver",
    description="Main webhook endpoint for receiving events from CSMS."
)
async def receive_csms_webhook(
    payload: CSMSWebhookPayload,
    db: AsyncSession = Depends(get_db),
    _body: bytes = Depends(verify_csms_signature),
) -> WebhookResponse:
    """
    Main webhook receiver for CSMS events.

    This endpoint receives generic webhook events from the CSMS system.
    Events are logged and processed based on their type.

    Args:
        payload: The webhook payload from CSMS
        db: Database session
        _body: Raw request body (used for signature verification)

    Returns:
        WebhookResponse indicating processing result
    """
    try:
        service = await get_webhook_service(db)
        result = await service.process_generic_webhook(payload)

        if not result.success:
            logger.warning(f"Webhook processing failed: {result.message}")

        return result

    except Exception as e:
        logger.exception(f"Error processing CSMS webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook: {str(e)}"
        )


@router.post(
    "/csms/events",
    response_model=WebhookResponse,
    responses={
        401: {"model": WebhookErrorResponse, "description": "Invalid signature"},
        422: {"model": WebhookErrorResponse, "description": "Invalid payload"},
        500: {"model": WebhookErrorResponse, "description": "Internal server error"},
    },
    summary="Charger Event Webhook",
    description="Webhook endpoint for charger event notifications (faults, status changes, etc.)."
)
async def receive_charger_event(
    payload: ChargerEventPayload,
    db: AsyncSession = Depends(get_db),
    _body: bytes = Depends(verify_csms_signature),
) -> WebhookResponse:
    """
    Webhook receiver for charger events.

    This endpoint receives charger-specific events from CSMS such as:
    - Status notifications
    - Fault events
    - Diagnostic events

    Critical faults will automatically create support tickets.

    Args:
        payload: The charger event payload
        db: Database session
        _body: Raw request body (used for signature verification)

    Returns:
        WebhookResponse indicating processing result, including any created ticket ID
    """
    try:
        service = await get_webhook_service(db)
        result = await service.process_charger_event(payload)

        if not result.success:
            logger.warning(f"Charger event processing failed: {result.message}")

        return result

    except Exception as e:
        logger.exception(f"Error processing charger event webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing charger event: {str(e)}"
        )


@router.post(
    "/csms/firmware",
    response_model=WebhookResponse,
    responses={
        401: {"model": WebhookErrorResponse, "description": "Invalid signature"},
        422: {"model": WebhookErrorResponse, "description": "Invalid payload"},
        500: {"model": WebhookErrorResponse, "description": "Internal server error"},
    },
    summary="Firmware Update Webhook",
    description="Webhook endpoint for firmware update status notifications."
)
async def receive_firmware_update(
    payload: FirmwareUpdatePayload,
    db: AsyncSession = Depends(get_db),
    _body: bytes = Depends(verify_csms_signature),
) -> WebhookResponse:
    """
    Webhook receiver for firmware update status.

    This endpoint receives firmware update status notifications from CSMS.
    It updates the corresponding firmware job reference and may update
    the charger's firmware version on successful completion.

    Status values:
    - scheduled: Update scheduled
    - downloading: Firmware downloading
    - downloaded: Firmware downloaded
    - installing: Firmware installing
    - installed: Update completed successfully
    - failed: Update failed
    - cancelled: Update cancelled

    Args:
        payload: The firmware update payload
        db: Database session
        _body: Raw request body (used for signature verification)

    Returns:
        WebhookResponse indicating processing result
    """
    try:
        service = await get_webhook_service(db)
        result = await service.process_firmware_update(payload)

        if not result.success:
            logger.warning(f"Firmware update processing failed: {result.message}")

        return result

    except Exception as e:
        logger.exception(f"Error processing firmware update webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing firmware update: {str(e)}"
        )


@router.post(
    "/csms/batch",
    response_model=BatchWebhookResponse,
    responses={
        401: {"model": WebhookErrorResponse, "description": "Invalid signature"},
        422: {"model": WebhookErrorResponse, "description": "Invalid payload"},
        500: {"model": WebhookErrorResponse, "description": "Internal server error"},
    },
    summary="Batch Webhook Receiver",
    description="Webhook endpoint for receiving multiple events in a single request."
)
async def receive_batch_webhook(
    payload: BatchWebhookPayload,
    db: AsyncSession = Depends(get_db),
    _body: bytes = Depends(verify_csms_signature),
) -> BatchWebhookResponse:
    """
    Batch webhook receiver for multiple CSMS events.

    This endpoint receives multiple events in a single request for
    efficient bulk processing.

    Args:
        payload: The batch webhook payload containing multiple events
        db: Database session
        _body: Raw request body (used for signature verification)

    Returns:
        BatchWebhookResponse with individual results for each event
    """
    results = []
    errors = []
    processed_count = 0
    failed_count = 0

    service = await get_webhook_service(db)

    for event in payload.events:
        try:
            result = await service.process_generic_webhook(event)
            results.append(result)

            if result.success:
                processed_count += 1
            else:
                failed_count += 1
                errors.append(WebhookErrorResponse(
                    success=False,
                    error="ProcessingError",
                    message=result.message,
                    details={"event_id": event.event_id}
                ))

        except Exception as e:
            failed_count += 1
            errors.append(WebhookErrorResponse(
                success=False,
                error="InternalError",
                message=str(e),
                details={"event_id": event.event_id}
            ))
            logger.exception(f"Error processing batch event {event.event_id}: {e}")

    return BatchWebhookResponse(
        success=failed_count == 0,
        batch_id=payload.batch_id,
        total_events=len(payload.events),
        processed_events=processed_count,
        failed_events=failed_count,
        results=results,
        errors=errors
    )


@router.get(
    "/csms/health",
    response_model=dict,
    summary="Webhook Health Check",
    description="Health check endpoint for CSMS webhook integration."
)
async def webhook_health_check() -> dict:
    """
    Health check for webhook endpoints.

    Returns a simple status to indicate the webhook receiver is operational.
    CSMS can use this endpoint to verify connectivity.

    Returns:
        Dict with status information
    """
    return {
        "status": "healthy",
        "service": "csms-webhook",
        "endpoints": {
            "generic": "/webhooks/csms",
            "events": "/webhooks/csms/events",
            "firmware": "/webhooks/csms/firmware",
            "batch": "/webhooks/csms/batch"
        }
    }
