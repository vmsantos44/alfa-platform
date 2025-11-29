"""
Dashboard API endpoints
Action alerts, stats, and overview data
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.database_models import (
    CandidateCache,
    ActionAlert,
    Interview,
    Task,
    AlertType,
    AlertPriority
)
from app.models.schemas import (
    DashboardResponse,
    DashboardStats,
    ActionAlertResponse,
    ActionAlertCreate,
    ResolveAlertRequest,
    InterviewResponse,
    TaskResponse,
    TodaySchedule,
    PipelineStage,
    CandidateSummary,
    SuccessResponse
)

router = APIRouter()


# ============================================
# Dashboard Overview
# ============================================

@router.get("/", response_model=DashboardResponse)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """
    Get full dashboard data including:
    - Stats (counts for key metrics)
    - Action alerts (unresolved items needing attention)
    - Today's schedule (interviews)
    - Pipeline overview
    - Overdue tasks
    """
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # Get dashboard stats
    stats = await get_dashboard_stats(db)

    # Get unresolved action alerts (high priority first)
    alerts_result = await db.execute(
        select(ActionAlert)
        .where(ActionAlert.is_resolved == False)
        .order_by(
            ActionAlert.priority.desc(),
            ActionAlert.created_at.desc()
        )
        .limit(10)
    )
    alerts = [ActionAlertResponse.model_validate(a) for a in alerts_result.scalars().all()]

    # Get today's interviews
    interviews_result = await db.execute(
        select(Interview)
        .where(
            and_(
                Interview.scheduled_date >= today_start,
                Interview.scheduled_date <= today_end,
                Interview.status.in_(["scheduled", "confirmed"])
            )
        )
        .order_by(Interview.scheduled_date)
    )
    today_interviews = [InterviewResponse.model_validate(i) for i in interviews_result.scalars().all()]

    # Get pipeline stages
    pipeline = await get_pipeline_overview(db)

    # Get overdue tasks
    overdue_result = await db.execute(
        select(Task)
        .where(
            and_(
                Task.due_date < datetime.utcnow(),
                Task.status.in_(["pending", "in_progress"])
            )
        )
        .order_by(Task.due_date)
        .limit(5)
    )
    overdue_tasks = [TaskResponse.model_validate(t) for t in overdue_result.scalars().all()]

    return DashboardResponse(
        stats=stats,
        action_alerts=alerts,
        today_schedule=TodaySchedule(
            interviews=today_interviews,
            total_count=len(today_interviews)
        ),
        pipeline=pipeline,
        overdue_tasks=overdue_tasks
    )


@router.get("/stats", response_model=DashboardStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get dashboard statistics only"""
    return await get_dashboard_stats(db)


async def get_dashboard_stats(db: AsyncSession) -> DashboardStats:
    """Calculate dashboard statistics"""
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # Count unresolved alerts
    alerts_count = await db.execute(
        select(func.count(ActionAlert.id))
        .where(ActionAlert.is_resolved == False)
    )
    needs_action = alerts_count.scalar() or 0

    # Count today's interviews
    today_interviews = await db.execute(
        select(func.count(Interview.id))
        .where(
            and_(
                Interview.scheduled_date >= today_start,
                Interview.scheduled_date <= today_end,
                Interview.status.in_(["scheduled", "confirmed"])
            )
        )
    )
    scheduled_today = today_interviews.scalar() or 0

    # Count active interpreters
    active_count = await db.execute(
        select(func.count(CandidateCache.id))
        .where(CandidateCache.stage == "Active")
    )
    active_interpreters = active_count.scalar() or 0

    # Count total candidates
    total = await db.execute(select(func.count(CandidateCache.id)))
    total_candidates = total.scalar() or 0

    # Pipeline stage counts
    stages = ["New Lead", "Screening", "Interview Scheduled", "Assessment", "Onboarding", "Active"]
    stage_counts = {}
    for stage in stages:
        count_result = await db.execute(
            select(func.count(CandidateCache.id))
            .where(CandidateCache.stage == stage)
        )
        stage_counts[stage] = count_result.scalar() or 0

    return DashboardStats(
        needs_action_count=needs_action,
        scheduled_today_count=scheduled_today,
        active_interpreters_count=active_interpreters,
        total_candidates=total_candidates,
        new_leads=stage_counts.get("New Lead", 0),
        screening=stage_counts.get("Screening", 0),
        interview=stage_counts.get("Interview Scheduled", 0),
        assessment=stage_counts.get("Assessment", 0),
        onboarding=stage_counts.get("Onboarding", 0),
        active=stage_counts.get("Active", 0)
    )


async def get_pipeline_overview(db: AsyncSession) -> List[PipelineStage]:
    """Get pipeline stages with counts"""
    stages = [
        "New Lead",
        "Screening",
        "Interview Scheduled",
        "Interview Completed",
        "Assessment",
        "Onboarding",
        "Active"
    ]

    pipeline = []
    for stage_name in stages:
        count_result = await db.execute(
            select(func.count(CandidateCache.id))
            .where(CandidateCache.stage == stage_name)
        )
        count = count_result.scalar() or 0

        pipeline.append(PipelineStage(
            stage=stage_name,
            count=count,
            candidates=[]  # We'll load candidates on demand
        ))

    return pipeline


# ============================================
# Action Alerts
# ============================================

@router.get("/alerts", response_model=List[ActionAlertResponse])
async def get_alerts(
    resolved: Optional[bool] = Query(False, description="Include resolved alerts"),
    alert_type: Optional[str] = Query(None, description="Filter by alert type"),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Get action alerts"""
    query = select(ActionAlert)

    if not resolved:
        query = query.where(ActionAlert.is_resolved == False)

    if alert_type:
        query = query.where(ActionAlert.alert_type == alert_type)

    query = query.order_by(
        ActionAlert.priority.desc(),
        ActionAlert.created_at.desc()
    ).limit(limit)

    result = await db.execute(query)
    return [ActionAlertResponse.model_validate(a) for a in result.scalars().all()]


@router.post("/alerts", response_model=ActionAlertResponse)
async def create_alert(
    alert: ActionAlertCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new action alert"""
    db_alert = ActionAlert(
        alert_type=alert.alert_type,
        priority=alert.priority,
        title=alert.title,
        description=alert.description,
        candidate_id=alert.candidate_id,
        candidate_name=alert.candidate_name,
        zoho_id=alert.zoho_id,
        zoho_module=alert.zoho_module,
        due_date=alert.due_date
    )
    db.add(db_alert)
    await db.commit()
    await db.refresh(db_alert)
    return ActionAlertResponse.model_validate(db_alert)


@router.post("/alerts/{alert_id}/resolve", response_model=ActionAlertResponse)
async def resolve_alert(
    alert_id: int,
    resolution: ResolveAlertRequest,
    db: AsyncSession = Depends(get_db)
):
    """Resolve an action alert"""
    result = await db.execute(
        select(ActionAlert).where(ActionAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_resolved = True
    alert.resolved_at = datetime.utcnow()
    alert.resolved_by = resolution.resolved_by
    alert.resolution_notes = resolution.resolution_notes

    await db.commit()
    await db.refresh(alert)
    return ActionAlertResponse.model_validate(alert)


@router.delete("/alerts/{alert_id}", response_model=SuccessResponse)
async def delete_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete an action alert"""
    result = await db.execute(
        select(ActionAlert).where(ActionAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    await db.delete(alert)
    await db.commit()
    return SuccessResponse(message="Alert deleted")


# ============================================
# Alert Generation (from CRM data)
# ============================================

@router.post("/alerts/generate", response_model=List[ActionAlertResponse])
async def generate_alerts(db: AsyncSession = Depends(get_db)):
    """
    Generate alerts from current data:
    - Candidates stuck in stage for 7+ days
    - Unresponsive candidates (no activity 7+ days)
    - Upcoming interviews needing confirmation
    - Overdue tasks
    """
    alerts_created = []
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    # Find stuck candidates
    stuck_result = await db.execute(
        select(CandidateCache)
        .where(
            and_(
                CandidateCache.stage_entered_date < seven_days_ago,
                CandidateCache.stage.in_(["Screening", "Interview Scheduled", "Assessment"])
            )
        )
    )
    stuck_candidates = stuck_result.scalars().all()

    for candidate in stuck_candidates:
        # Check if alert already exists
        existing = await db.execute(
            select(ActionAlert)
            .where(
                and_(
                    ActionAlert.zoho_id == candidate.zoho_id,
                    ActionAlert.alert_type == AlertType.STUCK_PIPELINE.value,
                    ActionAlert.is_resolved == False
                )
            )
        )
        if not existing.scalar_one_or_none():
            alert = ActionAlert(
                alert_type=AlertType.STUCK_PIPELINE.value,
                priority=AlertPriority.MEDIUM.value,
                title=f"{candidate.full_name} stuck in {candidate.stage}",
                description=f"Candidate has been in {candidate.stage} for {candidate.days_in_stage} days",
                candidate_id=candidate.id,
                candidate_name=candidate.full_name,
                zoho_id=candidate.zoho_id,
                zoho_module=candidate.zoho_module
            )
            db.add(alert)
            alerts_created.append(alert)

    # Find unresponsive candidates
    unresponsive_result = await db.execute(
        select(CandidateCache)
        .where(
            and_(
                CandidateCache.last_communication_date < seven_days_ago,
                CandidateCache.stage.notin_(["Active", "Inactive", "Rejected"])
            )
        )
    )
    unresponsive = unresponsive_result.scalars().all()

    for candidate in unresponsive:
        existing = await db.execute(
            select(ActionAlert)
            .where(
                and_(
                    ActionAlert.zoho_id == candidate.zoho_id,
                    ActionAlert.alert_type == AlertType.UNRESPONSIVE.value,
                    ActionAlert.is_resolved == False
                )
            )
        )
        if not existing.scalar_one_or_none():
            alert = ActionAlert(
                alert_type=AlertType.UNRESPONSIVE.value,
                priority=AlertPriority.HIGH.value,
                title=f"{candidate.full_name} - No response in 7+ days",
                description="Candidate has not responded to communications",
                candidate_id=candidate.id,
                candidate_name=candidate.full_name,
                zoho_id=candidate.zoho_id,
                zoho_module=candidate.zoho_module
            )
            db.add(alert)
            alerts_created.append(alert)

    # Find overdue tasks
    overdue_result = await db.execute(
        select(Task)
        .where(
            and_(
                Task.due_date < now,
                Task.status.in_(["pending", "in_progress"])
            )
        )
    )
    overdue_tasks = overdue_result.scalars().all()

    for task in overdue_tasks:
        existing = await db.execute(
            select(ActionAlert)
            .where(
                and_(
                    ActionAlert.title.contains(task.title),
                    ActionAlert.alert_type == AlertType.OVERDUE_TASK.value,
                    ActionAlert.is_resolved == False
                )
            )
        )
        if not existing.scalar_one_or_none():
            alert = ActionAlert(
                alert_type=AlertType.OVERDUE_TASK.value,
                priority=AlertPriority.HIGH.value,
                title=f"Overdue: {task.title}",
                description=f"Task was due {task.due_date.strftime('%Y-%m-%d')}",
                candidate_id=task.candidate_id,
                candidate_name=task.candidate_name,
                due_date=task.due_date
            )
            db.add(alert)
            alerts_created.append(alert)

    await db.commit()

    # Refresh and return
    for alert in alerts_created:
        await db.refresh(alert)

    return [ActionAlertResponse.model_validate(a) for a in alerts_created]
