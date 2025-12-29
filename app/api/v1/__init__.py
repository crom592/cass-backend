from fastapi import APIRouter
from app.api.v1 import auth, tickets, assets, assignments, worklogs, attachments, csms, reports, webhooks, sla, sse, notifications, metrics

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(tickets.router, prefix="/tickets", tags=["tickets"])
api_router.include_router(assets.router, prefix="/assets", tags=["assets"])
api_router.include_router(assignments.router, prefix="/assignments", tags=["assignments"])
api_router.include_router(worklogs.router, prefix="/worklogs", tags=["worklogs"])
api_router.include_router(attachments.router, prefix="/attachments", tags=["attachments"])
api_router.include_router(csms.router, prefix="/csms", tags=["csms"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(sla.router, prefix="/sla", tags=["sla"])
api_router.include_router(sse.router, prefix="/sse", tags=["sse"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(metrics.router, tags=["monitoring"])
