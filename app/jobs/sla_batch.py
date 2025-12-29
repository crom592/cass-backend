"""
SLA Batch Job Module

Provides scheduled background tasks for SLA calculation and breach detection.
"""

import asyncio
from datetime import datetime
from typing import Optional, Callable, Awaitable
import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.sla_service import SlaService


logger = logging.getLogger(__name__)


class SlaJobScheduler:
    """
    Scheduler for SLA batch processing jobs.

    Uses asyncio for lightweight background task scheduling.
    Runs SLA calculations every 5 minutes by default.
    """

    def __init__(
        self,
        interval_seconds: int = 300,  # 5 minutes default
        on_complete: Optional[Callable[[dict], Awaitable[None]]] = None
    ):
        """
        Initialize the SLA job scheduler.

        Args:
            interval_seconds: Time between job runs in seconds (default 300 = 5 minutes)
            on_complete: Optional async callback to execute after each job run
        """
        self.interval_seconds = interval_seconds
        self.on_complete = on_complete
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run: Optional[datetime] = None
        self._run_count = 0
        self._error_count = 0

    @asynccontextmanager
    async def get_db_session(self):
        """
        Create a database session for the batch job.

        Yields:
            AsyncSession: Database session
        """
        async with AsyncSessionLocal() as session:
            try:
                yield session
            finally:
                await session.close()

    async def run_sla_check(self) -> dict:
        """
        Execute a single SLA check run.

        Processes all open tickets and updates their SLA measurements.

        Returns:
            Summary of the processing results
        """
        logger.info("Starting SLA batch check...")
        start_time = datetime.utcnow()

        try:
            async with self.get_db_session() as db:
                sla_service = SlaService(db)
                result = await sla_service.process_all_open_tickets()

            result["started_at"] = start_time.isoformat()
            result["duration_seconds"] = (datetime.utcnow() - start_time).total_seconds()

            self._last_run = datetime.utcnow()
            self._run_count += 1

            logger.info(
                f"SLA batch check completed in {result['duration_seconds']:.2f}s: "
                f"processed={result['total_processed']}, breached={result['breached']}"
            )

            # Execute callback if provided
            if self.on_complete:
                try:
                    await self.on_complete(result)
                except Exception as e:
                    logger.error(f"Error in on_complete callback: {e}")

            return result

        except Exception as e:
            self._error_count += 1
            logger.error(f"SLA batch check failed: {e}")
            raise

    async def _scheduler_loop(self):
        """
        Internal scheduler loop that runs continuously.

        Executes SLA checks at the configured interval.
        """
        logger.info(
            f"SLA scheduler started with interval {self.interval_seconds} seconds"
        )

        while self._running:
            try:
                await self.run_sla_check()
            except Exception as e:
                logger.error(f"SLA scheduler error: {e}")

            # Wait for next interval
            await asyncio.sleep(self.interval_seconds)

        logger.info("SLA scheduler stopped")

    def start(self):
        """
        Start the scheduler.

        Creates an asyncio task that runs the scheduler loop.
        """
        if self._running:
            logger.warning("SLA scheduler is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("SLA scheduler task created")

    async def stop(self):
        """
        Stop the scheduler.

        Cancels the running task and waits for cleanup.
        """
        if not self._running:
            logger.warning("SLA scheduler is not running")
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("SLA scheduler stopped")

    def get_status(self) -> dict:
        """
        Get the current status of the scheduler.

        Returns:
            Dictionary with scheduler status information
        """
        return {
            "running": self._running,
            "interval_seconds": self.interval_seconds,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "run_count": self._run_count,
            "error_count": self._error_count,
            "next_run_in_seconds": self._calculate_next_run_seconds()
        }

    def _calculate_next_run_seconds(self) -> Optional[int]:
        """
        Calculate seconds until the next scheduled run.

        Returns:
            Seconds until next run, or None if scheduler is not running
        """
        if not self._running or not self._last_run:
            return None

        elapsed = (datetime.utcnow() - self._last_run).total_seconds()
        remaining = max(0, self.interval_seconds - elapsed)
        return int(remaining)


# Global scheduler instance
_sla_scheduler: Optional[SlaJobScheduler] = None


def get_sla_scheduler() -> SlaJobScheduler:
    """
    Get the global SLA scheduler instance.

    Creates a new instance if one doesn't exist.

    Returns:
        SlaJobScheduler instance
    """
    global _sla_scheduler
    if _sla_scheduler is None:
        _sla_scheduler = SlaJobScheduler()
    return _sla_scheduler


async def start_sla_scheduler():
    """
    Start the global SLA scheduler.

    Called during application startup.
    """
    scheduler = get_sla_scheduler()
    scheduler.start()
    logger.info("Global SLA scheduler started")


async def stop_sla_scheduler():
    """
    Stop the global SLA scheduler.

    Called during application shutdown.
    """
    global _sla_scheduler
    if _sla_scheduler:
        await _sla_scheduler.stop()
        _sla_scheduler = None
    logger.info("Global SLA scheduler stopped")


async def trigger_sla_recalculation() -> dict:
    """
    Manually trigger an SLA recalculation.

    Can be called from API endpoints for manual recalculation.

    Returns:
        Result of the SLA check
    """
    scheduler = get_sla_scheduler()
    return await scheduler.run_sla_check()


async def process_single_ticket_sla(ticket_id: str) -> dict:
    """
    Process SLA for a single ticket.

    Utility function for processing individual tickets.

    Args:
        ticket_id: The ticket ID to process

    Returns:
        SLA status for the ticket
    """
    async with AsyncSessionLocal() as db:
        try:
            sla_service = SlaService(db)
            await sla_service.update_sla_measurements(ticket_id)
            return await sla_service.get_sla_status_for_ticket(ticket_id)
        finally:
            await db.close()


class SlaViolationHandler:
    """
    Handler for SLA violation events.

    Can be extended to send notifications, create alerts, etc.
    """

    @staticmethod
    async def handle_breach(ticket_id: str, breach_type: str, details: dict):
        """
        Handle an SLA breach event.

        Override this method to implement custom breach handling:
        - Send email notifications
        - Create escalation tickets
        - Log to external systems
        - Trigger webhooks

        Args:
            ticket_id: The breached ticket ID
            breach_type: Type of breach ("response", "resolution", "both")
            details: Additional breach details
        """
        logger.warning(
            f"SLA VIOLATION: ticket_id={ticket_id}, type={breach_type}, "
            f"details={details}"
        )
        # TODO: Implement notification system
        # - Email to ticket owner
        # - Email to team lead
        # - Slack/Teams notification
        # - Dashboard alert

    @staticmethod
    async def handle_warning(ticket_id: str, warning_type: str, minutes_remaining: float):
        """
        Handle an SLA warning event.

        Called when SLA is approaching breach threshold.

        Args:
            ticket_id: The ticket ID
            warning_type: Type of warning ("response", "resolution")
            minutes_remaining: Minutes until breach
        """
        logger.info(
            f"SLA WARNING: ticket_id={ticket_id}, type={warning_type}, "
            f"minutes_remaining={minutes_remaining:.1f}"
        )
        # TODO: Implement warning notifications


async def check_sla_warnings():
    """
    Check for tickets approaching SLA breach.

    Identifies tickets that are within warning threshold of breach.
    Default warning threshold is 30 minutes before breach.
    """
    warning_threshold_minutes = 30

    async with AsyncSessionLocal() as db:
        try:
            sla_service = SlaService(db)
            open_tickets = await sla_service.get_open_tickets()

            for ticket in open_tickets:
                try:
                    breach_info = await sla_service.check_sla_breach(ticket.id)

                    # Check response time warning
                    response_remaining = breach_info.get("time_to_response_breach_minutes")
                    if response_remaining is not None and 0 < response_remaining <= warning_threshold_minutes:
                        await SlaViolationHandler.handle_warning(
                            ticket.id, "response", response_remaining
                        )

                    # Check resolution time warning
                    resolution_remaining = breach_info.get("time_to_resolution_breach_minutes")
                    if resolution_remaining is not None and 0 < resolution_remaining <= warning_threshold_minutes:
                        await SlaViolationHandler.handle_warning(
                            ticket.id, "resolution", resolution_remaining
                        )

                except Exception as e:
                    logger.error(f"Error checking warnings for ticket {ticket.id}: {e}")

        finally:
            await db.close()
