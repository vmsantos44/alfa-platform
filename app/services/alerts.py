"""
Alfa Operations Platform - System Alerts Service
Generates alerts based on candidate pipeline, interviews, and task data
"""
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.database_models import (
    CandidateCache, Interview, Task, ActionAlert,
    AlertType, AlertPriority
)


class AlertsService:
    """
    Generates system alerts for the dashboard.
    Alerts are computed dynamically from current data state.
    """

    # Configuration: days threshold for "stuck in stage"
    STUCK_STAGE_THRESHOLDS = {
        "New Candidate": 3,
        "Screening": 5,
        "Interview Scheduled": 7,
        "Interview Completed": 5,
        "Assessment": 7,
        "Onboarding": 14,
    }

    # Stages that should be checked for being stuck
    ACTIVE_STAGES = [
        "New Candidate", "Screening", "Interview Scheduled",
        "Interview Completed", "Assessment", "Onboarding"
    ]

    @classmethod
    async def get_all_alerts(
        cls,
        include_resolved: bool = False,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get all system alerts grouped by category.
        Returns computed alerts from current data state.
        """
        async with async_session() as db:
            alerts = {
                "no_shows": await cls._get_no_show_alerts(db),
                "stuck_candidates": await cls._get_stuck_candidate_alerts(db),
                "upcoming_interviews": await cls._get_upcoming_interview_alerts(db),
                "overdue_assessments": await cls._get_overdue_assessment_alerts(db),
                "pending_documents": await cls._get_pending_document_alerts(db),
            }

            # Calculate totals
            total_count = sum(len(v) for v in alerts.values())
            high_priority = sum(
                1 for category in alerts.values()
                for alert in category
                if alert.get("priority") == "high"
            )

            return {
                "alerts": alerts,
                "summary": {
                    "total": total_count,
                    "high_priority": high_priority,
                    "no_shows": len(alerts["no_shows"]),
                    "stuck_candidates": len(alerts["stuck_candidates"]),
                    "upcoming_interviews": len(alerts["upcoming_interviews"]),
                    "overdue_assessments": len(alerts["overdue_assessments"]),
                    "pending_documents": len(alerts["pending_documents"]),
                }
            }

    @classmethod
    async def get_alerts_flat(
        cls,
        limit: int = 20,
        priority: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all alerts as a flat list, sorted by priority and date.
        Useful for dashboard display.
        """
        all_alerts = await cls.get_all_alerts()

        # Flatten all alerts
        flat_list = []
        for category, alerts in all_alerts["alerts"].items():
            for alert in alerts:
                alert["category"] = category
                flat_list.append(alert)

        # Filter by priority if specified
        if priority:
            flat_list = [a for a in flat_list if a.get("priority") == priority]

        # Sort: high priority first, then by date
        priority_order = {"high": 0, "medium": 1, "low": 2}
        flat_list.sort(key=lambda x: (
            priority_order.get(x.get("priority", "medium"), 1),
            x.get("due_date") or x.get("created_at") or ""
        ))

        return flat_list[:limit]

    @classmethod
    async def _get_no_show_alerts(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get no-show interviews needing follow-up.
        Prioritizes recent no-shows that haven't been followed up.
        """
        query = select(Interview).where(
            and_(
                Interview.is_no_show == True,
                Interview.no_show_followup_sent == False
            )
        ).order_by(Interview.scheduled_date.desc()).limit(20)

        result = await db.execute(query)
        interviews = result.scalars().all()

        alerts = []
        for interview in interviews:
            days_since = (date.today() - interview.scheduled_date.date()).days if interview.scheduled_date else 0

            alerts.append({
                "id": f"no_show_{interview.id}",
                "type": AlertType.NO_SHOW.value,
                "priority": "high" if days_since <= 2 else "medium",
                "title": f"No-show: {interview.candidate_name}",
                "description": f"Missed interview on {interview.scheduled_date.strftime('%b %d')}. Follow-up needed.",
                "candidate_name": interview.candidate_name,
                "candidate_id": interview.candidate_id,
                "zoho_candidate_id": interview.zoho_candidate_id,
                "interview_id": interview.id,
                "scheduled_date": interview.scheduled_date.isoformat() if interview.scheduled_date else None,
                "days_since": days_since,
                "no_show_count": interview.no_show_count,
                "action_url": f"/candidates/{interview.candidate_id}" if interview.candidate_id else None,
                "action_label": "Follow Up"
            })

        return alerts

    @classmethod
    async def _get_stuck_candidate_alerts(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get candidates stuck in a stage longer than threshold.
        """
        today = date.today()
        alerts = []

        for stage, threshold_days in cls.STUCK_STAGE_THRESHOLDS.items():
            cutoff_date = datetime.combine(
                today - timedelta(days=threshold_days),
                datetime.min.time()
            )

            query = select(CandidateCache).where(
                and_(
                    CandidateCache.stage == stage,
                    or_(
                        CandidateCache.stage_entered_date <= cutoff_date,
                        and_(
                            CandidateCache.stage_entered_date.is_(None),
                            CandidateCache.days_in_stage >= threshold_days
                        )
                    )
                )
            ).order_by(CandidateCache.stage_entered_date.asc()).limit(10)

            result = await db.execute(query)
            candidates = result.scalars().all()

            for candidate in candidates:
                if candidate.stage_entered_date:
                    days_stuck = (today - candidate.stage_entered_date.date()).days
                else:
                    days_stuck = candidate.days_in_stage or threshold_days

                # Priority based on how long they've been stuck
                if days_stuck >= threshold_days * 2:
                    priority = "high"
                elif days_stuck >= threshold_days * 1.5:
                    priority = "medium"
                else:
                    priority = "low"

                alerts.append({
                    "id": f"stuck_{candidate.id}",
                    "type": AlertType.STUCK_PIPELINE.value,
                    "priority": priority,
                    "title": f"Stuck: {candidate.full_name}",
                    "description": f"In '{stage}' for {days_stuck} days (threshold: {threshold_days})",
                    "candidate_name": candidate.full_name,
                    "candidate_id": candidate.id,
                    "zoho_id": candidate.zoho_id,
                    "recruitment_owner": candidate.recruitment_owner,
                    "stage": stage,
                    "days_stuck": days_stuck,
                    "threshold_days": threshold_days,
                    "stage_entered_date": candidate.stage_entered_date.isoformat() if candidate.stage_entered_date else None,
                    "action_url": f"/candidates/{candidate.id}",
                    "action_label": "Review"
                })

        # Sort by priority then days stuck
        alerts.sort(key=lambda x: (
            {"high": 0, "medium": 1, "low": 2}.get(x["priority"], 1),
            -x["days_stuck"]
        ))

        return alerts[:20]

    @classmethod
    async def _get_upcoming_interview_alerts(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get today's and tomorrow's interviews.
        """
        today = date.today()
        tomorrow = today + timedelta(days=1)

        today_start = datetime.combine(today, datetime.min.time())
        tomorrow_end = datetime.combine(tomorrow, datetime.max.time())

        query = select(Interview).where(
            and_(
                Interview.scheduled_date >= today_start,
                Interview.scheduled_date <= tomorrow_end,
                Interview.status == "scheduled"
            )
        ).order_by(Interview.scheduled_date.asc())

        result = await db.execute(query)
        interviews = result.scalars().all()

        alerts = []
        now = datetime.now()

        for interview in interviews:
            is_today = interview.scheduled_date.date() == today
            is_soon = interview.scheduled_date <= now + timedelta(hours=2)

            if is_today and is_soon:
                priority = "high"
                time_label = "Starting soon"
            elif is_today:
                priority = "medium"
                time_label = "Today"
            else:
                priority = "low"
                time_label = "Tomorrow"

            alerts.append({
                "id": f"interview_{interview.id}",
                "type": "upcoming_interview",
                "priority": priority,
                "title": f"Interview: {interview.candidate_name}",
                "description": f"{time_label} at {interview.scheduled_date.strftime('%I:%M %p')}",
                "candidate_name": interview.candidate_name,
                "candidate_id": interview.candidate_id,
                "interview_id": interview.id,
                "scheduled_date": interview.scheduled_date.isoformat(),
                "interview_type": interview.interview_type,
                "interviewer": interview.interviewer,
                "is_today": is_today,
                "teams_link": interview.teams_meeting_link,
                "action_url": f"/scheduling",
                "action_label": "View"
            })

        return alerts

    @classmethod
    async def _get_overdue_assessment_alerts(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get candidates in assessment stage who haven't completed language assessment.
        Also checks for candidates past interview who need assessment.
        """
        assessment_stages = ["Assessment", "Interview Completed"]
        threshold_days = 5

        cutoff_date = datetime.combine(
            date.today() - timedelta(days=threshold_days),
            datetime.min.time()
        )

        query = select(CandidateCache).where(
            and_(
                CandidateCache.stage.in_(assessment_stages),
                CandidateCache.language_assessment_passed.is_(None),
                or_(
                    CandidateCache.stage_entered_date <= cutoff_date,
                    CandidateCache.days_in_stage >= threshold_days
                )
            )
        ).order_by(CandidateCache.stage_entered_date.asc()).limit(20)

        result = await db.execute(query)
        candidates = result.scalars().all()

        alerts = []
        today = date.today()

        for candidate in candidates:
            if candidate.stage_entered_date:
                days_waiting = (today - candidate.stage_entered_date.date()).days
            else:
                days_waiting = candidate.days_in_stage or threshold_days

            priority = "high" if days_waiting >= threshold_days * 2 else "medium"

            alerts.append({
                "id": f"assessment_{candidate.id}",
                "type": "overdue_assessment",
                "priority": priority,
                "title": f"Assessment: {candidate.full_name}",
                "description": f"Language assessment pending for {days_waiting} days",
                "candidate_name": candidate.full_name,
                "candidate_id": candidate.id,
                "zoho_id": candidate.zoho_id,
                "recruitment_owner": candidate.recruitment_owner,
                "stage": candidate.stage,
                "language": candidate.language,
                "days_waiting": days_waiting,
                "action_url": f"/candidates/{candidate.id}",
                "action_label": "Assess"
            })

        return alerts

    @classmethod
    async def _get_pending_document_alerts(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get candidates with pending document reviews.
        """
        query = select(CandidateCache).where(
            CandidateCache.has_pending_documents == True
        ).order_by(CandidateCache.updated_at.desc()).limit(20)

        result = await db.execute(query)
        candidates = result.scalars().all()

        alerts = []

        for candidate in candidates:
            # Check if they're in an active stage (higher priority)
            is_active_stage = candidate.stage in cls.ACTIVE_STAGES
            priority = "medium" if is_active_stage else "low"

            alerts.append({
                "id": f"documents_{candidate.id}",
                "type": AlertType.EXPIRED_DOCUMENT.value,
                "priority": priority,
                "title": f"Documents: {candidate.full_name}",
                "description": f"Pending document review ({candidate.stage})",
                "candidate_name": candidate.full_name,
                "candidate_id": candidate.id,
                "zoho_id": candidate.zoho_id,
                "recruitment_owner": candidate.recruitment_owner,
                "stage": candidate.stage,
                "action_url": f"/candidates/{candidate.id}",
                "action_label": "Review"
            })

        return alerts

    @classmethod
    async def get_alert_counts(cls) -> Dict[str, int]:
        """
        Get quick counts for badge display.
        """
        async with async_session() as db:
            # No-shows needing follow-up
            no_show_result = await db.execute(
                select(func.count(Interview.id)).where(
                    and_(
                        Interview.is_no_show == True,
                        Interview.no_show_followup_sent == False
                    )
                )
            )
            no_shows = no_show_result.scalar() or 0

            # Today's interviews
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())

            today_interviews_result = await db.execute(
                select(func.count(Interview.id)).where(
                    and_(
                        Interview.scheduled_date >= today_start,
                        Interview.scheduled_date <= today_end,
                        Interview.status == "scheduled"
                    )
                )
            )
            today_interviews = today_interviews_result.scalar() or 0

            # Stuck candidates (simplified: any with days_in_stage > 5)
            stuck_result = await db.execute(
                select(func.count(CandidateCache.id)).where(
                    and_(
                        CandidateCache.stage.in_(cls.ACTIVE_STAGES),
                        CandidateCache.days_in_stage > 5
                    )
                )
            )
            stuck = stuck_result.scalar() or 0

            # Pending documents
            docs_result = await db.execute(
                select(func.count(CandidateCache.id)).where(
                    CandidateCache.has_pending_documents == True
                )
            )
            pending_docs = docs_result.scalar() or 0

            total = no_shows + today_interviews + stuck + pending_docs

            return {
                "total": total,
                "no_shows": no_shows,
                "today_interviews": today_interviews,
                "stuck_candidates": stuck,
                "pending_documents": pending_docs
            }
