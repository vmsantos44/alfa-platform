"""
Reports API endpoints
Weekly summaries, pipeline metrics, and recruiter performance
"""
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
import csv
import io

from app.core.database import get_db
from app.models.database_models import CandidateCache, Interview, SyncLog

router = APIRouter()


# ============================================
# Weekly Summary Report
# ============================================

@router.get("/weekly-summary")
async def get_weekly_summary(
    weeks_back: int = Query(1, ge=1, le=12, description="Number of weeks to look back"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get weekly recruitment summary:
    - New candidates added
    - Interviews conducted
    - Stage transitions
    - Conversion rates
    """
    now = datetime.utcnow()

    # Calculate week boundaries
    weeks_data = []
    for i in range(weeks_back):
        week_end = now - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=7)

        # New candidates this week (based on zoho_created_time)
        new_candidates = await db.execute(
            select(func.count(CandidateCache.id))
            .where(
                and_(
                    CandidateCache.zoho_created_time >= week_start,
                    CandidateCache.zoho_created_time < week_end
                )
            )
        )
        new_count = new_candidates.scalar() or 0

        # Interviews completed this week
        interviews_completed = await db.execute(
            select(func.count(Interview.id))
            .where(
                and_(
                    Interview.scheduled_date >= week_start,
                    Interview.scheduled_date < week_end,
                    Interview.status == "completed"
                )
            )
        )
        interviews_count = interviews_completed.scalar() or 0

        # No-shows this week
        no_shows = await db.execute(
            select(func.count(Interview.id))
            .where(
                and_(
                    Interview.scheduled_date >= week_start,
                    Interview.scheduled_date < week_end,
                    Interview.is_no_show == True
                )
            )
        )
        no_show_count = no_shows.scalar() or 0

        # Candidates moved to Active this week
        activated = await db.execute(
            select(func.count(CandidateCache.id))
            .where(
                and_(
                    CandidateCache.stage == "Active",
                    CandidateCache.stage_entered_date >= week_start,
                    CandidateCache.stage_entered_date < week_end
                )
            )
        )
        activated_count = activated.scalar() or 0

        weeks_data.append({
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d"),
            "week_label": f"Week of {week_start.strftime('%b %d')}",
            "new_candidates": new_count,
            "interviews_completed": interviews_count,
            "no_shows": no_show_count,
            "activated": activated_count,
            "interview_completion_rate": round((interviews_count / (interviews_count + no_show_count) * 100), 1) if (interviews_count + no_show_count) > 0 else 0
        })

    # Reverse to show oldest first
    weeks_data.reverse()

    return {
        "weeks": weeks_data,
        "generated_at": now.isoformat()
    }


# ============================================
# Pipeline Metrics Report
# ============================================

@router.get("/pipeline-metrics")
async def get_pipeline_metrics(
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed pipeline metrics:
    - Candidates per stage
    - Average days in each stage
    - Conversion rates between stages
    """
    stages = [
        "New Candidate",
        "Screening",
        "Interview Scheduled",
        "Interview Completed",
        "Assessment",
        "Onboarding",
        "Active"
    ]

    metrics = []
    prev_count = None

    for stage in stages:
        # Count candidates in this stage
        count_result = await db.execute(
            select(func.count(CandidateCache.id))
            .where(CandidateCache.stage == stage)
        )
        count = count_result.scalar() or 0

        # Average days in stage
        avg_days_result = await db.execute(
            select(func.avg(CandidateCache.days_in_stage))
            .where(CandidateCache.stage == stage)
        )
        avg_days = avg_days_result.scalar() or 0

        # Calculate conversion rate from previous stage
        conversion_rate = None
        if prev_count and prev_count > 0:
            conversion_rate = round((count / prev_count) * 100, 1)

        metrics.append({
            "stage": stage,
            "count": count,
            "avg_days_in_stage": round(avg_days, 1),
            "conversion_from_previous": conversion_rate
        })

        prev_count = count

    # Overall funnel conversion (New Candidate -> Active)
    first_stage_count = metrics[0]["count"] if metrics else 0
    last_stage_count = metrics[-1]["count"] if metrics else 0
    overall_conversion = round((last_stage_count / first_stage_count) * 100, 1) if first_stage_count > 0 else 0

    return {
        "stages": metrics,
        "overall_conversion_rate": overall_conversion,
        "total_in_pipeline": sum(m["count"] for m in metrics)
    }


# ============================================
# Recruiter Performance Report
# ============================================

@router.get("/recruiters")
async def get_recruiters_list(
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of all recruiters (candidate owners) for filter dropdown
    """
    result = await db.execute(
        select(CandidateCache.candidate_owner)
        .where(CandidateCache.candidate_owner.isnot(None))
        .distinct()
        .order_by(CandidateCache.candidate_owner)
    )
    recruiters = [row[0] for row in result.all()]
    return {"recruiters": recruiters}


@router.get("/recruiter-performance")
async def get_recruiter_performance(
    days: int = Query(30, ge=7, le=365, description="Days to analyze"),
    recruiter: Optional[str] = Query(None, description="Filter by recruiter name"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recruiter performance metrics:
    - Candidates per recruiter
    - Stage distribution per recruiter
    - Activity metrics
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Build query with optional recruiter filter
    query = select(
        CandidateCache.candidate_owner,
        func.count(CandidateCache.id).label('total'),
        func.sum(case((CandidateCache.stage == 'Active', 1), else_=0)).label('active'),
        func.sum(case((CandidateCache.stage == 'Screening', 1), else_=0)).label('screening'),
        func.sum(case((CandidateCache.stage.in_(['Interview Scheduled', 'Interview Completed']), 1), else_=0)).label('interviewing'),
        func.sum(case((CandidateCache.stage == 'Onboarding', 1), else_=0)).label('onboarding'),
        func.sum(case((CandidateCache.stage == 'New Candidate', 1), else_=0)).label('new_candidate'),
        func.sum(case((CandidateCache.stage == 'Assessment', 1), else_=0)).label('assessment'),
        func.sum(case((CandidateCache.stage == 'Inactive', 1), else_=0)).label('inactive'),
        func.sum(case((CandidateCache.stage == 'Rejected', 1), else_=0)).label('rejected'),
        func.sum(case((CandidateCache.is_unresponsive == True, 1), else_=0)).label('unresponsive')
    ).where(CandidateCache.candidate_owner.isnot(None))

    if recruiter:
        query = query.where(CandidateCache.candidate_owner == recruiter)

    query = query.group_by(CandidateCache.candidate_owner).order_by(func.count(CandidateCache.id).desc())

    recruiters_result = await db.execute(query)

    recruiters = []
    for row in recruiters_result.all():
        total = row.total or 0
        active = row.active or 0

        recruiters.append({
            "name": row.candidate_owner,
            "total_candidates": total,
            "active": active,
            "new_candidate": row.new_candidate or 0,
            "screening": row.screening or 0,
            "interviewing": row.interviewing or 0,
            "assessment": row.assessment or 0,
            "onboarding": row.onboarding or 0,
            "inactive": row.inactive or 0,
            "rejected": row.rejected or 0,
            "unresponsive": row.unresponsive or 0,
            "activation_rate": round((active / total) * 100, 1) if total > 0 else 0
        })

    return {
        "period_days": days,
        "filter_recruiter": recruiter,
        "recruiters": recruiters,
        "total_recruiters": len(recruiters)
    }


# ============================================
# Source Analysis Report
# ============================================

@router.get("/source-analysis")
async def get_source_analysis(
    db: AsyncSession = Depends(get_db)
):
    """
    Analyze candidate sources and their effectiveness:
    - Candidates per source
    - Conversion rates by source
    """
    sources_result = await db.execute(
        select(
            CandidateCache.candidate_source,
            func.count(CandidateCache.id).label('total'),
            func.sum(case((CandidateCache.stage == 'Active', 1), else_=0)).label('active'),
            func.sum(case((CandidateCache.stage.in_(['Interview Scheduled', 'Interview Completed', 'Assessment', 'Onboarding', 'Active']), 1), else_=0)).label('progressed')
        )
        .where(CandidateCache.candidate_source.isnot(None))
        .group_by(CandidateCache.candidate_source)
        .order_by(func.count(CandidateCache.id).desc())
        .limit(15)
    )

    sources = []
    for row in sources_result.all():
        total = row.total or 0
        active = row.active or 0
        progressed = row.progressed or 0

        sources.append({
            "source": row.candidate_source,
            "total_candidates": total,
            "active": active,
            "progressed_past_screening": progressed,
            "activation_rate": round((active / total) * 100, 1) if total > 0 else 0,
            "progression_rate": round((progressed / total) * 100, 1) if total > 0 else 0
        })

    return {"sources": sources}


# ============================================
# Language Distribution Report
# ============================================

@router.get("/language-distribution")
async def get_language_distribution(
    db: AsyncSession = Depends(get_db)
):
    """
    Get language distribution with tier breakdown
    """
    languages_result = await db.execute(
        select(
            CandidateCache.language,
            func.count(CandidateCache.id).label('total'),
            func.sum(case((CandidateCache.tier == 'Tier 1', 1), else_=0)).label('tier1'),
            func.sum(case((CandidateCache.tier == 'Tier 2', 1), else_=0)).label('tier2'),
            func.sum(case((CandidateCache.tier == 'Tier 3', 1), else_=0)).label('tier3'),
            func.sum(case((CandidateCache.stage == 'Active', 1), else_=0)).label('active')
        )
        .where(CandidateCache.language.isnot(None))
        .group_by(CandidateCache.language)
        .order_by(func.count(CandidateCache.id).desc())
        .limit(20)
    )

    languages = []
    for row in languages_result.all():
        languages.append({
            "language": row.language,
            "total": row.total or 0,
            "tier_1": row.tier1 or 0,
            "tier_2": row.tier2 or 0,
            "tier_3": row.tier3 or 0,
            "active": row.active or 0
        })

    return {"languages": languages}


# ============================================
# Interview Statistics Report
# ============================================

@router.get("/interview-stats")
async def get_interview_stats(
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db)
):
    """
    Get interview statistics over time
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Total interviews
    total_result = await db.execute(
        select(func.count(Interview.id))
        .where(Interview.scheduled_date >= cutoff_date)
    )
    total = total_result.scalar() or 0

    # Completed
    completed_result = await db.execute(
        select(func.count(Interview.id))
        .where(
            and_(
                Interview.scheduled_date >= cutoff_date,
                Interview.status == "completed"
            )
        )
    )
    completed = completed_result.scalar() or 0

    # No-shows
    no_shows_result = await db.execute(
        select(func.count(Interview.id))
        .where(
            and_(
                Interview.scheduled_date >= cutoff_date,
                Interview.is_no_show == True
            )
        )
    )
    no_shows = no_shows_result.scalar() or 0

    # Cancelled
    cancelled_result = await db.execute(
        select(func.count(Interview.id))
        .where(
            and_(
                Interview.scheduled_date >= cutoff_date,
                Interview.status == "cancelled"
            )
        )
    )
    cancelled = cancelled_result.scalar() or 0

    # By outcome
    outcomes_result = await db.execute(
        select(Interview.outcome, func.count(Interview.id))
        .where(
            and_(
                Interview.scheduled_date >= cutoff_date,
                Interview.outcome.isnot(None)
            )
        )
        .group_by(Interview.outcome)
    )
    outcomes = {row[0]: row[1] for row in outcomes_result.all()}

    # By type
    types_result = await db.execute(
        select(Interview.interview_type, func.count(Interview.id))
        .where(Interview.scheduled_date >= cutoff_date)
        .group_by(Interview.interview_type)
    )
    by_type = {row[0]: row[1] for row in types_result.all()}

    return {
        "period_days": days,
        "total_scheduled": total,
        "completed": completed,
        "no_shows": no_shows,
        "cancelled": cancelled,
        "completion_rate": round((completed / total) * 100, 1) if total > 0 else 0,
        "no_show_rate": round((no_shows / total) * 100, 1) if total > 0 else 0,
        "outcomes": outcomes,
        "by_type": by_type
    }


# ============================================
# Export Endpoints
# ============================================

@router.get("/export/candidates")
async def export_candidates_csv(
    stage: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Export candidates to CSV"""
    query = select(CandidateCache)

    if stage:
        query = query.where(CandidateCache.stage == stage)

    query = query.order_by(CandidateCache.full_name)

    result = await db.execute(query)
    candidates = result.scalars().all()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Name", "Email", "Phone", "Stage", "Tier", "Language",
        "Recruitment Owner", "Assigned Client", "Days in Stage",
        "Last Activity", "Source", "Created Date"
    ])

    # Data rows
    for c in candidates:
        writer.writerow([
            c.full_name,
            c.email or "",
            c.phone or c.mobile or "",
            c.stage,
            c.tier or "",
            c.language or "",
            c.candidate_owner or "",
            c.assigned_client or "",
            c.days_in_stage,
            c.last_activity_date.strftime("%Y-%m-%d") if c.last_activity_date else "",
            c.candidate_source or "",
            c.zoho_created_time.strftime("%Y-%m-%d") if c.zoho_created_time else ""
        ])

    output.seek(0)

    filename = f"candidates_{stage or 'all'}_{datetime.utcnow().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/pipeline-report")
async def export_pipeline_report(
    db: AsyncSession = Depends(get_db)
):
    """Export pipeline metrics to CSV"""
    metrics = await get_pipeline_metrics(db)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Stage", "Count", "Avg Days in Stage", "Conversion from Previous (%)"])

    for stage in metrics["stages"]:
        writer.writerow([
            stage["stage"],
            stage["count"],
            stage["avg_days_in_stage"],
            stage["conversion_from_previous"] or "N/A"
        ])

    writer.writerow([])
    writer.writerow(["Overall Conversion Rate", f"{metrics['overall_conversion_rate']}%"])
    writer.writerow(["Total in Pipeline", metrics["total_in_pipeline"]])

    output.seek(0)

    filename = f"pipeline_report_{datetime.utcnow().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
