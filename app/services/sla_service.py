"""
SLA Service Module

Provides SLA calculation and breach detection functionality for tickets.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
import logging

from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from app.models.sla import SlaPolicy, SlaMeasurement, SlaStatus
from app.models.worklog import Worklog


logger = logging.getLogger(__name__)


class SlaService:
    """
    Service for managing SLA calculations and measurements.

    Provides methods for:
    - Calculating SLA metrics for tickets
    - Checking for SLA breaches
    - Updating SLA measurements
    - Managing SLA policies
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the SLA service.

        Args:
            db: Async database session
        """
        self.db = db

    async def get_sla_policy_for_ticket(
        self,
        ticket: Ticket
    ) -> Optional[SlaPolicy]:
        """
        Get the applicable SLA policy for a ticket based on its category and priority.

        First tries to find an exact match for category and priority.
        Falls back to default policies if no exact match is found.

        Args:
            ticket: The ticket to find a policy for

        Returns:
            SlaPolicy if found, None otherwise
        """
        # First, try to find exact match for category and priority
        result = await self.db.execute(
            select(SlaPolicy).where(
                and_(
                    SlaPolicy.tenant_id == ticket.tenant_id,
                    SlaPolicy.category == ticket.category.value,
                    SlaPolicy.priority == ticket.priority.value,
                    SlaPolicy.is_active == True
                )
            )
        )
        policy = result.scalar_one_or_none()

        if policy:
            return policy

        # Fall back to policy matching only priority (any category)
        result = await self.db.execute(
            select(SlaPolicy).where(
                and_(
                    SlaPolicy.tenant_id == ticket.tenant_id,
                    SlaPolicy.priority == ticket.priority.value,
                    SlaPolicy.is_active == True
                )
            ).order_by(SlaPolicy.created_at.asc())
        )
        policy = result.scalars().first()

        return policy

    async def get_ticket_with_relations(
        self,
        ticket_id: str
    ) -> Optional[Ticket]:
        """
        Get a ticket with its SLA measurements and worklogs loaded.

        Args:
            ticket_id: The ID of the ticket

        Returns:
            Ticket with loaded relations if found, None otherwise
        """
        result = await self.db.execute(
            select(Ticket)
            .options(
                selectinload(Ticket.sla_measurements),
                selectinload(Ticket.worklogs)
            )
            .where(Ticket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def get_first_response_time(
        self,
        ticket: Ticket
    ) -> Optional[datetime]:
        """
        Get the timestamp of the first response for a ticket.

        First response is determined by:
        1. First worklog entry (excluding internal notes from system)
        2. First status change from NEW to any other status

        Args:
            ticket: The ticket to check

        Returns:
            Datetime of first response if found, None otherwise
        """
        # Get the first worklog entry (public response)
        result = await self.db.execute(
            select(Worklog)
            .where(
                and_(
                    Worklog.ticket_id == ticket.id,
                    Worklog.is_internal == False
                )
            )
            .order_by(Worklog.created_at.asc())
            .limit(1)
        )
        first_worklog = result.scalar_one_or_none()

        if first_worklog:
            return first_worklog.created_at

        # If no worklog, check if ticket has been assigned
        if ticket.current_status != TicketStatus.NEW:
            # Check status history for first transition from NEW
            from app.models.ticket import TicketStatusHistory
            result = await self.db.execute(
                select(TicketStatusHistory)
                .where(
                    and_(
                        TicketStatusHistory.ticket_id == ticket.id,
                        TicketStatusHistory.from_status == TicketStatus.NEW
                    )
                )
                .order_by(TicketStatusHistory.changed_at.asc())
                .limit(1)
            )
            first_transition = result.scalar_one_or_none()
            if first_transition:
                return first_transition.changed_at

        return None

    async def calculate_sla_for_ticket(
        self,
        ticket_id: str
    ) -> Dict[str, Any]:
        """
        Calculate SLA metrics for a specific ticket.

        Computes response time, resolution time, and breach status.

        Args:
            ticket_id: The ID of the ticket

        Returns:
            Dictionary containing SLA metrics:
            - ticket_id: str
            - policy_id: str or None
            - response_target_minutes: int or None
            - resolution_target_minutes: int or None
            - actual_response_minutes: float or None
            - actual_resolution_minutes: float or None
            - response_breached: bool
            - resolution_breached: bool
            - overall_status: SlaStatus
        """
        ticket = await self.get_ticket_with_relations(ticket_id)

        if not ticket:
            raise ValueError(f"Ticket not found: {ticket_id}")

        # Get applicable policy
        policy = await self.get_sla_policy_for_ticket(ticket)

        if not policy:
            logger.warning(f"No SLA policy found for ticket {ticket_id}")
            return {
                "ticket_id": ticket_id,
                "policy_id": None,
                "response_target_minutes": None,
                "resolution_target_minutes": None,
                "actual_response_minutes": None,
                "actual_resolution_minutes": None,
                "response_breached": False,
                "resolution_breached": False,
                "overall_status": SlaStatus.ACTIVE
            }

        now = datetime.utcnow()

        # Calculate response time
        first_response_at = await self.get_first_response_time(ticket)
        response_target_at = ticket.opened_at + timedelta(minutes=policy.response_time_minutes)

        actual_response_minutes = None
        response_breached = False

        if first_response_at:
            actual_response_minutes = (first_response_at - ticket.opened_at).total_seconds() / 60
            response_breached = first_response_at > response_target_at
        else:
            # No response yet, check if target time has passed
            response_breached = now > response_target_at
            if not response_breached:
                actual_response_minutes = (now - ticket.opened_at).total_seconds() / 60

        # Calculate resolution time
        resolution_target_at = ticket.opened_at + timedelta(minutes=policy.resolution_time_minutes)
        actual_resolution_minutes = None
        resolution_breached = False

        if ticket.resolved_at:
            actual_resolution_minutes = (ticket.resolved_at - ticket.opened_at).total_seconds() / 60
            resolution_breached = ticket.resolved_at > resolution_target_at
        elif ticket.current_status in [TicketStatus.CLOSED, TicketStatus.CANCELLED]:
            # Consider closed/cancelled as resolved for SLA purposes
            actual_resolution_minutes = (ticket.closed_at or now - ticket.opened_at).total_seconds() / 60 if ticket.closed_at else None
            resolution_breached = (ticket.closed_at or now) > resolution_target_at if ticket.closed_at else now > resolution_target_at
        else:
            # Ticket still open, check if target time has passed
            resolution_breached = now > resolution_target_at

        # Determine overall SLA status
        overall_status = SlaStatus.ACTIVE
        if ticket.current_status in [TicketStatus.RESOLVED, TicketStatus.CLOSED]:
            if response_breached or resolution_breached:
                overall_status = SlaStatus.BREACHED
            else:
                overall_status = SlaStatus.MET
        elif ticket.current_status == TicketStatus.CANCELLED:
            overall_status = SlaStatus.CANCELLED
        elif response_breached or resolution_breached:
            overall_status = SlaStatus.BREACHED

        return {
            "ticket_id": ticket_id,
            "policy_id": policy.id,
            "response_target_minutes": policy.response_time_minutes,
            "resolution_target_minutes": policy.resolution_time_minutes,
            "response_target_at": response_target_at,
            "resolution_target_at": resolution_target_at,
            "first_response_at": first_response_at,
            "actual_response_minutes": actual_response_minutes,
            "actual_resolution_minutes": actual_resolution_minutes,
            "response_breached": response_breached,
            "resolution_breached": resolution_breached,
            "overall_status": overall_status
        }

    async def check_sla_breach(
        self,
        ticket_id: str
    ) -> Dict[str, Any]:
        """
        Check if SLA is breached for a specific ticket.

        Args:
            ticket_id: The ID of the ticket

        Returns:
            Dictionary containing breach status:
            - is_breached: bool
            - response_breached: bool
            - resolution_breached: bool
            - breach_type: str or None ("response", "resolution", "both", None)
            - time_to_response_breach_minutes: float or None
            - time_to_resolution_breach_minutes: float or None
        """
        sla_data = await self.calculate_sla_for_ticket(ticket_id)

        response_breached = sla_data.get("response_breached", False)
        resolution_breached = sla_data.get("resolution_breached", False)
        is_breached = response_breached or resolution_breached

        # Determine breach type
        breach_type = None
        if response_breached and resolution_breached:
            breach_type = "both"
        elif response_breached:
            breach_type = "response"
        elif resolution_breached:
            breach_type = "resolution"

        # Calculate time to breach
        now = datetime.utcnow()
        time_to_response_breach = None
        time_to_resolution_breach = None

        if sla_data.get("response_target_at") and not sla_data.get("first_response_at"):
            time_to_response_breach = (sla_data["response_target_at"] - now).total_seconds() / 60

        if sla_data.get("resolution_target_at"):
            ticket = await self.get_ticket_with_relations(ticket_id)
            if ticket and ticket.current_status not in [TicketStatus.RESOLVED, TicketStatus.CLOSED, TicketStatus.CANCELLED]:
                time_to_resolution_breach = (sla_data["resolution_target_at"] - now).total_seconds() / 60

        return {
            "ticket_id": ticket_id,
            "is_breached": is_breached,
            "response_breached": response_breached,
            "resolution_breached": resolution_breached,
            "breach_type": breach_type,
            "time_to_response_breach_minutes": time_to_response_breach,
            "time_to_resolution_breach_minutes": time_to_resolution_breach,
            "overall_status": sla_data.get("overall_status")
        }

    async def update_sla_measurements(
        self,
        ticket_id: str
    ) -> Optional[SlaMeasurement]:
        """
        Update or create SLA measurements for a ticket.

        Creates a new measurement record if none exists,
        otherwise updates the existing record.

        Args:
            ticket_id: The ID of the ticket

        Returns:
            Updated or created SlaMeasurement object
        """
        ticket = await self.get_ticket_with_relations(ticket_id)

        if not ticket:
            raise ValueError(f"Ticket not found: {ticket_id}")

        # Get applicable policy
        policy = await self.get_sla_policy_for_ticket(ticket)

        if not policy:
            logger.warning(f"No SLA policy found for ticket {ticket_id}, skipping measurement update")
            return None

        # Calculate SLA metrics
        sla_data = await self.calculate_sla_for_ticket(ticket_id)

        # Get or create measurement
        result = await self.db.execute(
            select(SlaMeasurement).where(SlaMeasurement.ticket_id == ticket_id)
        )
        measurement = result.scalar_one_or_none()

        now = datetime.utcnow()

        if not measurement:
            # Create new measurement
            measurement = SlaMeasurement(
                ticket_id=ticket_id,
                policy_id=policy.id,
                status=sla_data["overall_status"],
                response_target_at=sla_data["response_target_at"],
                resolution_target_at=sla_data["resolution_target_at"],
                first_response_at=sla_data.get("first_response_at"),
                resolved_at=ticket.resolved_at,
                response_breached=sla_data["response_breached"],
                resolution_breached=sla_data["resolution_breached"],
                started_at=ticket.opened_at
            )

            # Set breached_at timestamp if breached
            if sla_data["response_breached"] or sla_data["resolution_breached"]:
                measurement.breached_at = now

            self.db.add(measurement)
            logger.info(f"Created SLA measurement for ticket {ticket_id}")
        else:
            # Update existing measurement
            measurement.status = sla_data["overall_status"]
            measurement.first_response_at = sla_data.get("first_response_at")
            measurement.resolved_at = ticket.resolved_at
            measurement.response_breached = sla_data["response_breached"]
            measurement.resolution_breached = sla_data["resolution_breached"]

            # Set breached_at timestamp if newly breached
            if (sla_data["response_breached"] or sla_data["resolution_breached"]) and not measurement.breached_at:
                measurement.breached_at = now

            logger.info(f"Updated SLA measurement for ticket {ticket_id}")

        # Update ticket's sla_breached flag
        ticket.sla_breached = sla_data["response_breached"] or sla_data["resolution_breached"]

        await self.db.commit()
        await self.db.refresh(measurement)

        return measurement

    async def get_open_tickets(
        self,
        tenant_id: Optional[str] = None
    ) -> List[Ticket]:
        """
        Get all open tickets that need SLA checking.

        Open tickets are those not in RESOLVED, CLOSED, or CANCELLED status.

        Args:
            tenant_id: Optional tenant ID to filter by

        Returns:
            List of open tickets
        """
        closed_statuses = [
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
            TicketStatus.CANCELLED
        ]

        query = select(Ticket).where(
            ~Ticket.current_status.in_(closed_statuses)
        )

        if tenant_id:
            query = query.where(Ticket.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def process_all_open_tickets(self) -> Dict[str, Any]:
        """
        Process SLA calculations for all open tickets.

        This is the main method used by the batch job.

        Returns:
            Summary of processing results:
            - total_processed: int
            - breached: int
            - within_sla: int
            - errors: List[str]
        """
        open_tickets = await self.get_open_tickets()

        total_processed = 0
        breached = 0
        within_sla = 0
        errors = []

        for ticket in open_tickets:
            try:
                measurement = await self.update_sla_measurements(ticket.id)
                total_processed += 1

                if measurement and (measurement.response_breached or measurement.resolution_breached):
                    breached += 1
                    logger.warning(
                        f"SLA breach detected for ticket {ticket.ticket_number}: "
                        f"response_breached={measurement.response_breached}, "
                        f"resolution_breached={measurement.resolution_breached}"
                    )
                else:
                    within_sla += 1

            except Exception as e:
                error_msg = f"Error processing ticket {ticket.id}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

        summary = {
            "total_processed": total_processed,
            "breached": breached,
            "within_sla": within_sla,
            "errors": errors,
            "processed_at": datetime.utcnow().isoformat()
        }

        logger.info(
            f"SLA batch processing completed: processed={total_processed}, "
            f"breached={breached}, within_sla={within_sla}, errors={len(errors)}"
        )

        return summary

    async def get_sla_status_for_ticket(
        self,
        ticket_id: str
    ) -> Dict[str, Any]:
        """
        Get comprehensive SLA status for a ticket.

        Combines calculation data with existing measurements.

        Args:
            ticket_id: The ID of the ticket

        Returns:
            Complete SLA status information
        """
        ticket = await self.get_ticket_with_relations(ticket_id)

        if not ticket:
            raise ValueError(f"Ticket not found: {ticket_id}")

        # Get SLA calculation
        sla_data = await self.calculate_sla_for_ticket(ticket_id)

        # Get existing measurement
        result = await self.db.execute(
            select(SlaMeasurement)
            .options(selectinload(SlaMeasurement.policy))
            .where(SlaMeasurement.ticket_id == ticket_id)
        )
        measurement = result.scalar_one_or_none()

        # Build response
        response = {
            "ticket_id": ticket_id,
            "ticket_number": ticket.ticket_number,
            "current_status": ticket.current_status.value,
            "priority": ticket.priority.value,
            "category": ticket.category.value,
            "opened_at": ticket.opened_at.isoformat() if ticket.opened_at else None,
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            "sla_breached": ticket.sla_breached,
            "policy": None,
            "measurement": None,
            "calculation": sla_data
        }

        if measurement and measurement.policy:
            response["policy"] = {
                "id": measurement.policy.id,
                "response_time_minutes": measurement.policy.response_time_minutes,
                "resolution_time_minutes": measurement.policy.resolution_time_minutes
            }
            response["measurement"] = {
                "id": measurement.id,
                "status": measurement.status.value,
                "response_target_at": measurement.response_target_at.isoformat() if measurement.response_target_at else None,
                "resolution_target_at": measurement.resolution_target_at.isoformat() if measurement.resolution_target_at else None,
                "first_response_at": measurement.first_response_at.isoformat() if measurement.first_response_at else None,
                "resolved_at": measurement.resolved_at.isoformat() if measurement.resolved_at else None,
                "response_breached": measurement.response_breached,
                "resolution_breached": measurement.resolution_breached,
                "breached_at": measurement.breached_at.isoformat() if measurement.breached_at else None
            }

        return response

    async def get_policies(
        self,
        tenant_id: str,
        active_only: bool = True
    ) -> List[SlaPolicy]:
        """
        Get SLA policies for a tenant.

        Args:
            tenant_id: The tenant ID
            active_only: If True, only return active policies

        Returns:
            List of SLA policies
        """
        query = select(SlaPolicy).where(SlaPolicy.tenant_id == tenant_id)

        if active_only:
            query = query.where(SlaPolicy.is_active == True)

        query = query.order_by(SlaPolicy.priority, SlaPolicy.category)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def create_policy(
        self,
        tenant_id: str,
        category: str,
        priority: str,
        response_time_minutes: int,
        resolution_time_minutes: int
    ) -> SlaPolicy:
        """
        Create a new SLA policy.

        Args:
            tenant_id: The tenant ID
            category: Ticket category
            priority: Ticket priority
            response_time_minutes: Target response time in minutes
            resolution_time_minutes: Target resolution time in minutes

        Returns:
            Created SlaPolicy object
        """
        policy = SlaPolicy(
            tenant_id=tenant_id,
            category=category,
            priority=priority,
            response_time_minutes=response_time_minutes,
            resolution_time_minutes=resolution_time_minutes,
            is_active=True
        )

        self.db.add(policy)
        await self.db.commit()
        await self.db.refresh(policy)

        logger.info(
            f"Created SLA policy: tenant={tenant_id}, category={category}, "
            f"priority={priority}, response={response_time_minutes}min, "
            f"resolution={resolution_time_minutes}min"
        )

        return policy

    async def update_policy(
        self,
        policy_id: str,
        **updates
    ) -> Optional[SlaPolicy]:
        """
        Update an existing SLA policy.

        Args:
            policy_id: The policy ID
            **updates: Fields to update

        Returns:
            Updated SlaPolicy object or None if not found
        """
        result = await self.db.execute(
            select(SlaPolicy).where(SlaPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            return None

        allowed_fields = [
            "response_time_minutes",
            "resolution_time_minutes",
            "is_active"
        ]

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(policy, field, value)

        await self.db.commit()
        await self.db.refresh(policy)

        return policy

    async def initialize_sla_for_new_ticket(
        self,
        ticket: Ticket
    ) -> Optional[SlaMeasurement]:
        """
        Initialize SLA measurement when a new ticket is created.

        Should be called from ticket creation endpoint.

        Args:
            ticket: The newly created ticket

        Returns:
            Created SlaMeasurement or None if no policy applies
        """
        policy = await self.get_sla_policy_for_ticket(ticket)

        if not policy:
            logger.info(f"No SLA policy found for new ticket {ticket.id}")
            return None

        now = datetime.utcnow()

        measurement = SlaMeasurement(
            ticket_id=ticket.id,
            policy_id=policy.id,
            status=SlaStatus.ACTIVE,
            response_target_at=ticket.opened_at + timedelta(minutes=policy.response_time_minutes),
            resolution_target_at=ticket.opened_at + timedelta(minutes=policy.resolution_time_minutes),
            started_at=ticket.opened_at
        )

        self.db.add(measurement)
        await self.db.commit()
        await self.db.refresh(measurement)

        logger.info(
            f"Initialized SLA measurement for ticket {ticket.id}: "
            f"response_target={measurement.response_target_at}, "
            f"resolution_target={measurement.resolution_target_at}"
        )

        return measurement
