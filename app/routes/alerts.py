"""
System Alerts API endpoints
Provides alerts for no-shows, stuck candidates, upcoming interviews, etc.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.alerts import AlertsService
from app.models.database_models import Interview
from app.models.schemas import SuccessResponse

router = APIRouter()


@router.get("/")
async def get_all_alerts(
    limit: int = Query(50, le=100),
    include_resolved: bool = Query(False)
):
    """
    Get all system alerts grouped by category.
    Returns computed alerts based on current data state.
    """
    return await AlertsService.get_all_alerts(
        include_resolved=include_resolved,
        limit=limit
    )


@router.get("/flat")
async def get_alerts_flat(
    limit: int = Query(20, le=100),
    priority: Optional[str] = Query(None, description="Filter by priority: high, medium, low")
):
    """
    Get all alerts as a flat list, sorted by priority.
    Useful for dashboard display.
    """
    return await AlertsService.get_alerts_flat(limit=limit, priority=priority)


@router.get("/counts")
async def get_alert_counts():
    """
    Get quick counts for badge display.
    Returns counts for each alert category.
    """
    return await AlertsService.get_alert_counts()


@router.get("/no-shows")
async def get_no_show_alerts(
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get no-show interviews needing follow-up.
    """
    from app.services.alerts import AlertsService

    async with db.begin():
        alerts = await AlertsService._get_no_show_alerts(db)
    return alerts[:limit]


@router.get("/stuck-candidates")
async def get_stuck_candidate_alerts(
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get candidates stuck in pipeline stages.
    """
    from app.services.alerts import AlertsService

    async with db.begin():
        alerts = await AlertsService._get_stuck_candidate_alerts(db)
    return alerts[:limit]


@router.get("/upcoming-interviews")
async def get_upcoming_interview_alerts(
    db: AsyncSession = Depends(get_db)
):
    """
    Get today's and tomorrow's scheduled interviews.
    """
    from app.services.alerts import AlertsService

    async with db.begin():
        alerts = await AlertsService._get_upcoming_interview_alerts(db)
    return alerts


@router.get("/overdue-assessments")
async def get_overdue_assessment_alerts(
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get candidates with overdue language assessments.
    """
    from app.services.alerts import AlertsService

    async with db.begin():
        alerts = await AlertsService._get_overdue_assessment_alerts(db)
    return alerts[:limit]


@router.get("/pending-documents")
async def get_pending_document_alerts(
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get candidates with pending document reviews.
    """
    from app.services.alerts import AlertsService

    async with db.begin():
        alerts = await AlertsService._get_pending_document_alerts(db)
    return alerts[:limit]


# ============================================
# Alert Actions
# ============================================

@router.post("/no-shows/{interview_id}/mark-followed-up", response_model=SuccessResponse)
async def mark_no_show_followed_up(
    interview_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a no-show interview as followed up.
    Removes it from the alerts list.
    """
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    if not interview.is_no_show:
        raise HTTPException(status_code=400, detail="Interview is not marked as no-show")

    interview.no_show_followup_sent = True

    await db.commit()

    return SuccessResponse(
        message=f"Marked follow-up complete for {interview.candidate_name}"
    )
