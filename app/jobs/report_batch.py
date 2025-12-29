"""
Report Snapshot Batch Jobs

Scheduled batch jobs for generating daily, weekly, and monthly report snapshots.
Uses APScheduler for job scheduling with async support.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.tenant import Tenant
from app.services.report_service import ReportService

logger = logging.getLogger(__name__)

# APScheduler instance (will be initialized in setup_report_scheduler)
scheduler = None


async def get_active_tenants(db: AsyncSession) -> List[Tenant]:
    """Get all active tenants for batch processing."""
    query = select(Tenant).where(Tenant.is_active == True)
    result = await db.execute(query)
    return list(result.scalars().all())


async def run_daily_snapshot_job(target_date: Optional[date] = None) -> dict:
    """
    Generate daily snapshots for all active tenants.

    Runs at midnight, generates snapshots for the previous day.

    Args:
        target_date: Optional specific date to generate. Defaults to yesterday.

    Returns:
        dict: Summary of job execution with success/failure counts
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    logger.info(f"Starting daily snapshot job for date: {target_date}")

    success_count = 0
    failure_count = 0
    errors = []

    async with AsyncSessionLocal() as db:
        try:
            tenants = await get_active_tenants(db)
            logger.info(f"Processing {len(tenants)} active tenants for daily snapshots")

            report_service = ReportService(db)

            for tenant in tenants:
                try:
                    snapshot = await report_service.generate_daily_snapshot(
                        tenant_id=tenant.id,
                        target_date=target_date
                    )
                    success_count += 1
                    logger.info(
                        f"Generated daily snapshot {snapshot.id} for tenant {tenant.id}"
                    )
                except Exception as e:
                    failure_count += 1
                    error_msg = f"Failed to generate daily snapshot for tenant {tenant.id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)

        except Exception as e:
            logger.error(f"Daily snapshot job failed: {str(e)}", exc_info=True)
            raise

    summary = {
        "job_type": "daily",
        "target_date": target_date.isoformat(),
        "total_tenants": success_count + failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "errors": errors,
        "completed_at": datetime.utcnow().isoformat()
    }

    logger.info(
        f"Daily snapshot job completed: {success_count} success, {failure_count} failures"
    )

    return summary


async def run_weekly_snapshot_job(week_start: Optional[date] = None) -> dict:
    """
    Generate weekly snapshots for all active tenants.

    Runs on Monday, generates snapshots for the previous week (Monday to Sunday).

    Args:
        week_start: Optional specific week start (Monday) to generate.
                   Defaults to previous week's Monday.

    Returns:
        dict: Summary of job execution with success/failure counts
    """
    if week_start is None:
        # Get previous week's Monday
        today = date.today()
        days_since_monday = today.weekday()
        # Go back to this Monday, then subtract 7 days for last week's Monday
        week_start = today - timedelta(days=days_since_monday + 7)

    logger.info(f"Starting weekly snapshot job for week starting: {week_start}")

    success_count = 0
    failure_count = 0
    errors = []

    async with AsyncSessionLocal() as db:
        try:
            tenants = await get_active_tenants(db)
            logger.info(f"Processing {len(tenants)} active tenants for weekly snapshots")

            report_service = ReportService(db)

            for tenant in tenants:
                try:
                    snapshot = await report_service.generate_weekly_snapshot(
                        tenant_id=tenant.id,
                        week_start=week_start
                    )
                    success_count += 1
                    logger.info(
                        f"Generated weekly snapshot {snapshot.id} for tenant {tenant.id}"
                    )
                except Exception as e:
                    failure_count += 1
                    error_msg = f"Failed to generate weekly snapshot for tenant {tenant.id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)

        except Exception as e:
            logger.error(f"Weekly snapshot job failed: {str(e)}", exc_info=True)
            raise

    summary = {
        "job_type": "weekly",
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "total_tenants": success_count + failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "errors": errors,
        "completed_at": datetime.utcnow().isoformat()
    }

    logger.info(
        f"Weekly snapshot job completed: {success_count} success, {failure_count} failures"
    )

    return summary


async def run_monthly_snapshot_job(
    year: Optional[int] = None,
    month: Optional[int] = None
) -> dict:
    """
    Generate monthly snapshots for all active tenants.

    Runs on the 1st of each month, generates snapshots for the previous month.

    Args:
        year: Optional specific year. Defaults to previous month's year.
        month: Optional specific month (1-12). Defaults to previous month.

    Returns:
        dict: Summary of job execution with success/failure counts
    """
    if year is None or month is None:
        # Get previous month
        today = date.today()
        first_of_current_month = date(today.year, today.month, 1)
        last_of_previous_month = first_of_current_month - timedelta(days=1)
        year = last_of_previous_month.year
        month = last_of_previous_month.month

    logger.info(f"Starting monthly snapshot job for: {year}-{month:02d}")

    success_count = 0
    failure_count = 0
    errors = []

    async with AsyncSessionLocal() as db:
        try:
            tenants = await get_active_tenants(db)
            logger.info(f"Processing {len(tenants)} active tenants for monthly snapshots")

            report_service = ReportService(db)

            for tenant in tenants:
                try:
                    snapshot = await report_service.generate_monthly_snapshot(
                        tenant_id=tenant.id,
                        year=year,
                        month=month
                    )
                    success_count += 1
                    logger.info(
                        f"Generated monthly snapshot {snapshot.id} for tenant {tenant.id}"
                    )
                except Exception as e:
                    failure_count += 1
                    error_msg = f"Failed to generate monthly snapshot for tenant {tenant.id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)

        except Exception as e:
            logger.error(f"Monthly snapshot job failed: {str(e)}", exc_info=True)
            raise

    summary = {
        "job_type": "monthly",
        "year": year,
        "month": month,
        "total_tenants": success_count + failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "errors": errors,
        "completed_at": datetime.utcnow().isoformat()
    }

    logger.info(
        f"Monthly snapshot job completed: {success_count} success, {failure_count} failures"
    )

    return summary


def setup_report_scheduler(app):
    """
    Set up the APScheduler for report batch jobs.

    This function configures and starts the scheduler with the following jobs:
    - Daily snapshot: Runs at 00:05 every day
    - Weekly snapshot: Runs at 00:10 every Monday
    - Monthly snapshot: Runs at 00:15 on the 1st of each month

    Args:
        app: The FastAPI application instance
    """
    global scheduler

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.jobstores.memory import MemoryJobStore
        from apscheduler.executors.asyncio import AsyncIOExecutor
    except ImportError:
        logger.warning(
            "APScheduler not installed. Report batch jobs will not be scheduled. "
            "Install with: pip install apscheduler"
        )
        return None

    # Configure scheduler
    jobstores = {
        'default': MemoryJobStore()
    }
    executors = {
        'default': AsyncIOExecutor()
    }
    job_defaults = {
        'coalesce': True,  # Combine multiple missed runs into one
        'max_instances': 1,  # Only one instance of each job at a time
        'misfire_grace_time': 3600  # Allow 1 hour grace time for misfired jobs
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone='UTC'
    )

    # Add daily snapshot job - runs at 00:05 UTC every day
    scheduler.add_job(
        run_daily_snapshot_job,
        trigger=CronTrigger(hour=0, minute=5),
        id='daily_snapshot',
        name='Daily Report Snapshot',
        replace_existing=True
    )
    logger.info("Scheduled daily snapshot job for 00:05 UTC")

    # Add weekly snapshot job - runs at 00:10 UTC every Monday
    scheduler.add_job(
        run_weekly_snapshot_job,
        trigger=CronTrigger(day_of_week='mon', hour=0, minute=10),
        id='weekly_snapshot',
        name='Weekly Report Snapshot',
        replace_existing=True
    )
    logger.info("Scheduled weekly snapshot job for Monday 00:10 UTC")

    # Add monthly snapshot job - runs at 00:15 UTC on the 1st of each month
    scheduler.add_job(
        run_monthly_snapshot_job,
        trigger=CronTrigger(day=1, hour=0, minute=15),
        id='monthly_snapshot',
        name='Monthly Report Snapshot',
        replace_existing=True
    )
    logger.info("Scheduled monthly snapshot job for 1st of month 00:15 UTC")

    # Register startup/shutdown handlers
    @app.on_event("startup")
    async def start_scheduler():
        scheduler.start()
        logger.info("Report batch scheduler started")

    @app.on_event("shutdown")
    async def stop_scheduler():
        scheduler.shutdown(wait=False)
        logger.info("Report batch scheduler stopped")

    return scheduler


def get_scheduler_status() -> dict:
    """Get the current status of the scheduler and its jobs."""
    global scheduler

    if scheduler is None:
        return {
            "status": "not_initialized",
            "jobs": []
        }

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })

    return {
        "status": "running" if scheduler.running else "stopped",
        "jobs": jobs
    }
