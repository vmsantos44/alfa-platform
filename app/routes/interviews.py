"""
Interview Management API endpoints
Schedule interviews, track no-shows, manage rescheduling
"""
from datetime import datetime, timedelta, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.database_models import Interview, CandidateCache, ActionAlert, AlertType, AlertPriority
from app.models.schemas import (
    InterviewResponse,
    InterviewCreate,
    InterviewUpdate,
    MarkNoShowRequest,
    SuccessResponse
)

router = APIRouter()


# ============================================
# Interview CRUD
# ============================================

@router.get("/", response_model=List[InterviewResponse])
async def list_interviews(
    status: Optional[str] = Query(None, description="Filter by status"),
    date_from: Optional[date] = Query(None, description="Start date"),
    date_to: Optional[date] = Query(None, description="End date"),
    candidate_id: Optional[int] = Query(None, description="Filter by candidate"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    """List interviews with optional filters"""
    query = select(Interview)

    conditions = []
    if status:
        conditions.append(Interview.status == status)
    if date_from:
        conditions.append(Interview.scheduled_date >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conditions.append(Interview.scheduled_date <= datetime.combine(date_to, datetime.max.time()))
    if candidate_id:
        conditions.append(Interview.candidate_id == candidate_id)

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(Interview.scheduled_date.desc()).limit(limit)

    result = await db.execute(query)
    return [InterviewResponse.model_validate(i) for i in result.scalars().all()]


@router.get("/today", response_model=List[InterviewResponse])
async def get_today_interviews(db: AsyncSession = Depends(get_db)):
    """Get all interviews scheduled for today"""
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    result = await db.execute(
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
    return [InterviewResponse.model_validate(i) for i in result.scalars().all()]


@router.get("/upcoming", response_model=List[InterviewResponse])
async def get_upcoming_interviews(
    days: int = Query(7, description="Number of days ahead"),
    db: AsyncSession = Depends(get_db)
):
    """Get upcoming interviews for the next X days"""
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)

    result = await db.execute(
        select(Interview)
        .where(
            and_(
                Interview.scheduled_date >= now,
                Interview.scheduled_date <= end_date,
                Interview.status.in_(["scheduled", "confirmed"])
            )
        )
        .order_by(Interview.scheduled_date)
    )
    return [InterviewResponse.model_validate(i) for i in result.scalars().all()]


@router.get("/no-shows", response_model=List[InterviewResponse])
async def get_no_shows(
    pending_followup: bool = Query(True, description="Only show those needing follow-up"),
    days: Optional[int] = Query(None, description="Filter to last N days (7, 30, 90, or None for all)"),
    limit: int = Query(50, le=200, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """Get no-show interviews with optional date filtering and pagination"""
    query = select(Interview).where(Interview.is_no_show == True)

    if pending_followup:
        query = query.where(Interview.no_show_followup_sent == False)

    if days is not None:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        query = query.where(Interview.scheduled_date >= cutoff_date)

    query = query.order_by(Interview.scheduled_date.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    return [InterviewResponse.model_validate(i) for i in result.scalars().all()]


@router.get("/no-shows/count")
async def get_no_shows_count(
    pending_followup: bool = Query(True, description="Only count those needing follow-up"),
    days: Optional[int] = Query(None, description="Filter to last N days"),
    db: AsyncSession = Depends(get_db)
):
    """Get count of no-show interviews for pagination"""
    query = select(func.count(Interview.id)).where(Interview.is_no_show == True)

    if pending_followup:
        query = query.where(Interview.no_show_followup_sent == False)

    if days is not None:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        query = query.where(Interview.scheduled_date >= cutoff_date)

    result = await db.execute(query)
    return {"count": result.scalar() or 0}


@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview(
    interview_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a single interview by ID"""
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    return InterviewResponse.model_validate(interview)


@router.post("/", response_model=InterviewResponse)
async def create_interview(
    interview: InterviewCreate,
    db: AsyncSession = Depends(get_db)
):
    """Schedule a new interview"""
    # If candidate_id provided, get candidate details
    candidate_name = interview.candidate_name
    candidate_email = interview.candidate_email
    candidate_phone = interview.candidate_phone

    if interview.candidate_id:
        result = await db.execute(
            select(CandidateCache).where(CandidateCache.id == interview.candidate_id)
        )
        candidate = result.scalar_one_or_none()
        if candidate:
            candidate_name = candidate.full_name
            candidate_email = candidate.email or candidate_email
            candidate_phone = candidate.phone or candidate_phone

    db_interview = Interview(
        candidate_id=interview.candidate_id,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        candidate_phone=candidate_phone,
        zoho_candidate_id=interview.zoho_candidate_id,
        scheduled_date=interview.scheduled_date,
        duration_minutes=interview.duration_minutes,
        interview_type=interview.interview_type,
        interviewer=interview.interviewer,
        notes=interview.notes,
        status="scheduled"
    )

    db.add(db_interview)
    await db.commit()
    await db.refresh(db_interview)

    return InterviewResponse.model_validate(db_interview)


@router.put("/{interview_id}", response_model=InterviewResponse)
async def update_interview(
    interview_id: int,
    update: InterviewUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update an interview"""
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Track if rescheduling
    if update.scheduled_date and update.scheduled_date != interview.scheduled_date:
        if not interview.original_date:
            interview.original_date = interview.scheduled_date
        interview.reschedule_count += 1
        interview.reschedule_reason = update.reschedule_reason

    # Update fields
    if update.scheduled_date:
        interview.scheduled_date = update.scheduled_date
    if update.status:
        interview.status = update.status
    if update.is_no_show is not None:
        interview.is_no_show = update.is_no_show
    if update.outcome:
        interview.outcome = update.outcome
    if update.notes:
        interview.notes = update.notes

    interview.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(interview)

    return InterviewResponse.model_validate(interview)


@router.delete("/{interview_id}", response_model=SuccessResponse)
async def delete_interview(
    interview_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete/cancel an interview"""
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    await db.delete(interview)
    await db.commit()

    return SuccessResponse(message="Interview deleted")


# ============================================
# No-Show Management
# ============================================

@router.post("/{interview_id}/no-show", response_model=InterviewResponse)
async def mark_no_show(
    interview_id: int,
    request: MarkNoShowRequest,
    db: AsyncSession = Depends(get_db)
):
    """Mark an interview as a no-show"""
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview.is_no_show = True
    interview.no_show_count += 1
    interview.status = "no_show"

    if request.notes:
        interview.notes = (interview.notes or "") + f"\n[No-show] {request.notes}"

    interview.updated_at = datetime.utcnow()

    # Create action alert for follow-up
    alert = ActionAlert(
        alert_type=AlertType.NO_SHOW.value,
        priority=AlertPriority.HIGH.value,
        title=f"No-show: {interview.candidate_name}",
        description=f"Interview scheduled for {interview.scheduled_date.strftime('%Y-%m-%d %H:%M')} - needs reschedule",
        candidate_id=interview.candidate_id,
        candidate_name=interview.candidate_name
    )
    db.add(alert)

    # Update candidate as potentially unresponsive if multiple no-shows
    if interview.candidate_id and interview.no_show_count >= 2:
        candidate_result = await db.execute(
            select(CandidateCache).where(CandidateCache.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()
        if candidate:
            candidate.is_unresponsive = True

    await db.commit()
    await db.refresh(interview)

    return InterviewResponse.model_validate(interview)


@router.post("/{interview_id}/reschedule", response_model=InterviewResponse)
async def reschedule_interview(
    interview_id: int,
    new_date: datetime = Query(..., description="New scheduled date/time"),
    reason: Optional[str] = Query(None, description="Reason for rescheduling"),
    db: AsyncSession = Depends(get_db)
):
    """Reschedule an interview"""
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Store original date if first reschedule
    if not interview.original_date:
        interview.original_date = interview.scheduled_date

    interview.scheduled_date = new_date
    interview.reschedule_count += 1
    interview.reschedule_reason = reason
    interview.status = "scheduled"
    interview.is_no_show = False  # Reset no-show flag
    interview.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(interview)

    return InterviewResponse.model_validate(interview)


@router.post("/{interview_id}/complete", response_model=InterviewResponse)
async def complete_interview(
    interview_id: int,
    outcome: str = Query(..., description="Outcome: passed, failed, needs_review"),
    notes: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Mark an interview as completed"""
    valid_outcomes = ["passed", "failed", "needs_review", "pending"]
    if outcome not in valid_outcomes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outcome. Must be one of: {', '.join(valid_outcomes)}"
        )

    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview.status = "completed"
    interview.outcome = outcome
    if notes:
        interview.notes = (interview.notes or "") + f"\n[Completed] {notes}"
    interview.updated_at = datetime.utcnow()

    # If passed, move candidate to next stage
    if outcome == "passed" and interview.candidate_id:
        candidate_result = await db.execute(
            select(CandidateCache).where(CandidateCache.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()
        if candidate and candidate.stage == "Interview Scheduled":
            candidate.stage = "Interview Completed"
            candidate.stage_entered_date = datetime.utcnow()
            candidate.days_in_stage = 0

    await db.commit()
    await db.refresh(interview)

    return InterviewResponse.model_validate(interview)


@router.post("/{interview_id}/followup-sent", response_model=SuccessResponse)
async def mark_followup_sent(
    interview_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Mark that no-show follow-up has been sent"""
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview.no_show_followup_sent = True
    interview.updated_at = datetime.utcnow()

    await db.commit()

    return SuccessResponse(message="Follow-up marked as sent")


# ============================================
# Calendar View Data
# ============================================

@router.get("/calendar/{year}/{month}")
async def get_calendar_data(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db)
):
    """Get interview data for calendar view"""
    # Calculate month boundaries
    first_day = datetime(year, month, 1)
    if month == 12:
        last_day = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    else:
        last_day = datetime(year, month + 1, 1) - timedelta(seconds=1)

    result = await db.execute(
        select(Interview)
        .where(
            and_(
                Interview.scheduled_date >= first_day,
                Interview.scheduled_date <= last_day
            )
        )
        .order_by(Interview.scheduled_date)
    )
    interviews = result.scalars().all()

    # Group by date
    calendar_data = {}
    for interview in interviews:
        date_key = interview.scheduled_date.strftime("%Y-%m-%d")
        if date_key not in calendar_data:
            calendar_data[date_key] = []
        calendar_data[date_key].append({
            "id": interview.id,
            "time": interview.scheduled_date.strftime("%H:%M"),
            "candidate_name": interview.candidate_name,
            "type": interview.interview_type,
            "status": interview.status,
            "is_no_show": interview.is_no_show
        })

    return {
        "year": year,
        "month": month,
        "interviews": calendar_data,
        "total_count": len(interviews)
    }


# ============================================
# Statistics
# ============================================

@router.get("/stats/summary")
async def get_interview_stats(db: AsyncSession = Depends(get_db)):
    """Get interview statistics"""
    now = datetime.utcnow()
    today = now.date()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Total interviews
    total_result = await db.execute(select(func.count(Interview.id)))
    total = total_result.scalar() or 0

    # Today's count
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    today_result = await db.execute(
        select(func.count(Interview.id))
        .where(and_(
            Interview.scheduled_date >= today_start,
            Interview.scheduled_date <= today_end
        ))
    )
    today_count = today_result.scalar() or 0

    # This week
    week_result = await db.execute(
        select(func.count(Interview.id))
        .where(Interview.scheduled_date >= week_ago)
    )
    week_count = week_result.scalar() or 0

    # No-shows this month
    no_show_result = await db.execute(
        select(func.count(Interview.id))
        .where(and_(
            Interview.is_no_show == True,
            Interview.scheduled_date >= month_ago
        ))
    )
    no_shows = no_show_result.scalar() or 0

    # Completion rate - only count PAST interviews (not future scheduled ones)
    completed_result = await db.execute(
        select(func.count(Interview.id))
        .where(and_(
            Interview.status == "completed",
            Interview.scheduled_date >= month_ago,
            Interview.scheduled_date <= now
        ))
    )
    completed = completed_result.scalar() or 0

    # Count past interviews only (scheduled_date <= now) - excludes future appointments
    past_interviews_result = await db.execute(
        select(func.count(Interview.id))
        .where(and_(
            Interview.scheduled_date >= month_ago,
            Interview.scheduled_date <= now
        ))
    )
    past_interviews = past_interviews_result.scalar() or 0

    # Completion rate = completed / (completed + no_shows) for past events
    # If no past interviews, show 0%
    completion_rate = (completed / past_interviews * 100) if past_interviews > 0 else 0

    return {
        "total_interviews": total,
        "today": today_count,
        "this_week": week_count,
        "no_shows_this_month": no_shows,
        "completed_this_month": completed,
        "completion_rate": round(completion_rate, 1)
    }
