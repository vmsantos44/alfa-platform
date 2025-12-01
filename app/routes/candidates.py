"""
Candidate Pipeline API endpoints
Manage candidates through recruitment stages
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.database_models import CandidateCache, ActionAlert, Interview, Task, CandidateNote
from app.models.schemas import (
    CandidateResponse,
    CandidateSummary,
    CandidateDetailResponse,
    CandidateNoteCreate,
    CandidateNoteResponse,
    PipelineStage,
    SuccessResponse,
    InterviewResponse,
    TaskResponse
)
from app.integrations.zoho.crm import get_crm_record_url

router = APIRouter()


# ============================================
# Pipeline Overview
# ============================================

@router.get("/pipeline", response_model=List[PipelineStage])
async def get_pipeline(
    include_candidates: bool = Query(False, description="Include candidate details"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get pipeline overview with candidate counts per stage.
    Optionally include candidate details.
    """
    stages = [
        "New Candidate",
        "Screening",
        "Interview Scheduled",
        "Interview Completed",
        "Assessment",
        "Onboarding",
        "Active",
        "Inactive",
        "Rejected"
    ]

    pipeline = []
    for stage_name in stages:
        count_result = await db.execute(
            select(func.count(CandidateCache.id))
            .where(CandidateCache.stage == stage_name)
        )
        count = count_result.scalar() or 0

        candidates = []
        if include_candidates and count > 0:
            candidates_result = await db.execute(
                select(CandidateCache)
                .where(CandidateCache.stage == stage_name)
                .order_by(CandidateCache.stage_entered_date.desc())
                .limit(50)
            )
            candidates = [
                CandidateSummary(
                    id=c.id,
                    zoho_id=c.zoho_id,
                    full_name=c.full_name,
                    stage=c.stage,
                    days_in_stage=c.days_in_stage,
                    is_unresponsive=c.is_unresponsive,
                    has_pending_documents=c.has_pending_documents,
                    needs_training=c.needs_training,
                    tier=c.tier,
                    languages=c.languages
                )
                for c in candidates_result.scalars().all()
            ]

        pipeline.append(PipelineStage(
            stage=stage_name,
            count=count,
            candidates=candidates
        ))

    return pipeline


# ============================================
# Filter Options (for populating dropdowns)
# ============================================

@router.get("/filter-options")
async def get_filter_options(db: AsyncSession = Depends(get_db)):
    """Get available filter options (languages, owners, etc.)"""
    # Get unique languages
    lang_result = await db.execute(
        select(CandidateCache.languages)
        .where(CandidateCache.languages.isnot(None))
        .distinct()
    )
    all_languages = set()
    for row in lang_result.scalars().all():
        if row:
            # Split languages by common separators
            for lang in row.replace(";", ",").split(","):
                lang = lang.strip()
                if lang:
                    all_languages.add(lang)

    # Get unique candidate owners
    owner_result = await db.execute(
        select(CandidateCache.candidate_owner)
        .where(CandidateCache.candidate_owner.isnot(None))
        .distinct()
    )
    owners = [o for o in owner_result.scalars().all() if o]

    # Get unique recruitment owners
    recruitment_owner_result = await db.execute(
        select(CandidateCache.recruitment_owner)
        .where(CandidateCache.recruitment_owner.isnot(None))
        .distinct()
    )
    recruitment_owners = [o for o in recruitment_owner_result.scalars().all() if o]

    # Get stage counts
    stage_counts = {}
    for stage in ["New Candidate", "Screening", "Interview Scheduled", "Interview Completed",
                  "Assessment", "Onboarding", "Active", "Inactive", "Rejected"]:
        count_result = await db.execute(
            select(func.count(CandidateCache.id))
            .where(CandidateCache.stage == stage)
        )
        stage_counts[stage] = count_result.scalar() or 0

    # Get unique tiers
    tier_result = await db.execute(
        select(CandidateCache.tier)
        .where(CandidateCache.tier.isnot(None))
        .distinct()
    )
    tiers = sorted([t for t in tier_result.scalars().all() if t])

    # Get unique states
    state_result = await db.execute(
        select(CandidateCache.state)
        .where(CandidateCache.state.isnot(None))
        .distinct()
    )
    states = sorted([s for s in state_result.scalars().all() if s])

    return {
        "languages": sorted(list(all_languages)),
        "owners": sorted(owners),
        "recruitment_owners": sorted(recruitment_owners),
        "stages": stage_counts,
        "tiers": tiers,
        "states": states
    }


# ============================================
# Bulk Operations (MUST be before /{candidate_id} route)
# ============================================

@router.get("/stuck", response_model=List[CandidateResponse])
async def get_stuck_candidates(
    days: int = Query(7, description="Days in stage threshold"),
    db: AsyncSession = Depends(get_db)
):
    """Get candidates stuck in a stage for X+ days"""
    result = await db.execute(
        select(CandidateCache)
        .where(
            and_(
                CandidateCache.days_in_stage >= days,
                CandidateCache.stage.in_(["Screening", "Interview Scheduled", "Assessment", "Onboarding"])
            )
        )
        .order_by(CandidateCache.days_in_stage.desc())
    )
    candidates = result.scalars().all()

    return [
        CandidateResponse(
            id=c.id,
            zoho_id=c.zoho_id,
            zoho_module=c.zoho_module,
            full_name=c.full_name,
            email=c.email,
            phone=c.phone,
            stage=c.stage,
            assigned_client=c.assigned_client,
            tier=c.tier,
            languages=c.languages,
            last_activity_date=c.last_activity_date,
            last_communication_date=c.last_communication_date,
            days_in_stage=c.days_in_stage,
            is_unresponsive=c.is_unresponsive,
            has_pending_documents=c.has_pending_documents,
            needs_training=c.needs_training,
            zoho_url=get_crm_record_url(c.zoho_module, c.zoho_id)
        )
        for c in candidates
    ]


@router.get("/unresponsive", response_model=List[CandidateResponse])
async def get_unresponsive_candidates(
    db: AsyncSession = Depends(get_db)
):
    """Get all unresponsive candidates"""
    result = await db.execute(
        select(CandidateCache)
        .where(CandidateCache.is_unresponsive == True)
        .order_by(CandidateCache.last_communication_date)
    )
    candidates = result.scalars().all()

    return [
        CandidateResponse(
            id=c.id,
            zoho_id=c.zoho_id,
            zoho_module=c.zoho_module,
            full_name=c.full_name,
            email=c.email,
            phone=c.phone,
            stage=c.stage,
            assigned_client=c.assigned_client,
            tier=c.tier,
            languages=c.languages,
            last_activity_date=c.last_activity_date,
            last_communication_date=c.last_communication_date,
            days_in_stage=c.days_in_stage,
            is_unresponsive=c.is_unresponsive,
            has_pending_documents=c.has_pending_documents,
            needs_training=c.needs_training,
            zoho_url=get_crm_record_url(c.zoho_module, c.zoho_id)
        )
        for c in candidates
    ]


# ============================================
# Candidate CRUD
# ============================================

@router.get("/", response_model=List[CandidateResponse])
async def list_candidates(
    stage: Optional[str] = Query(None, description="Filter by stage (comma-separated for multi)"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    unresponsive: Optional[bool] = Query(None, description="Filter unresponsive"),
    pending_docs: Optional[bool] = Query(None, description="Filter pending documents"),
    needs_training: Optional[bool] = Query(None, description="Filter needs training"),
    lang_assessment_passed: Optional[bool] = Query(None, description="Filter by language assessment passed"),
    bgv_passed: Optional[bool] = Query(None, description="Filter by background check passed"),
    system_specs_approved: Optional[bool] = Query(None, description="Filter by system specs approved"),
    offer_accepted: Optional[bool] = Query(None, description="Filter by offer accepted"),
    days_min: Optional[int] = Query(None, description="Minimum days in stage"),
    days_max: Optional[int] = Query(None, description="Maximum days in stage"),
    language: Optional[str] = Query(None, description="Filter by language (comma-separated)"),
    owner: Optional[str] = Query(None, description="Filter by owner (comma-separated)"),
    tier: Optional[str] = Query(None, description="Filter by tier (comma-separated)"),
    state: Optional[str] = Query(None, description="Filter by state (comma-separated)"),
    date_from: Optional[str] = Query(None, description="Date added from (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Date added to (YYYY-MM-DD)"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """List candidates with advanced filters"""
    query = select(CandidateCache)

    # Apply filters
    conditions = []

    # Multi-select stage filter
    if stage:
        stages = [s.strip() for s in stage.split(",")]
        if len(stages) == 1:
            conditions.append(CandidateCache.stage == stages[0])
        else:
            conditions.append(CandidateCache.stage.in_(stages))

    # Search filter
    if search:
        search_term = f"%{search}%"
        conditions.append(
            or_(
                CandidateCache.full_name.ilike(search_term),
                CandidateCache.email.ilike(search_term)
            )
        )

    # Boolean filters
    if unresponsive is not None:
        conditions.append(CandidateCache.is_unresponsive == unresponsive)
    if pending_docs is not None:
        conditions.append(CandidateCache.has_pending_documents == pending_docs)
    if needs_training is not None:
        conditions.append(CandidateCache.needs_training == needs_training)
    if lang_assessment_passed is not None:
        conditions.append(CandidateCache.language_assessment_passed == lang_assessment_passed)
    if bgv_passed is not None:
        conditions.append(CandidateCache.bgv_passed == bgv_passed)
    if system_specs_approved is not None:
        conditions.append(CandidateCache.system_specs_approved == system_specs_approved)
    if offer_accepted is not None:
        conditions.append(CandidateCache.offer_accepted == offer_accepted)

    # Days in stage range
    if days_min is not None:
        conditions.append(CandidateCache.days_in_stage >= days_min)
    if days_max is not None:
        conditions.append(CandidateCache.days_in_stage <= days_max)

    # Language filter (search in languages field)
    if language:
        languages = [l.strip() for l in language.split(",")]
        lang_conditions = [CandidateCache.languages.ilike(f"%{lang}%") for lang in languages]
        conditions.append(or_(*lang_conditions))

    # Owner filter
    if owner:
        owners = [o.strip() for o in owner.split(",")]
        if len(owners) == 1:
            conditions.append(CandidateCache.candidate_owner == owners[0])
        else:
            conditions.append(CandidateCache.candidate_owner.in_(owners))

    # Tier filter
    if tier:
        tiers = [t.strip() for t in tier.split(",")]
        if len(tiers) == 1:
            conditions.append(CandidateCache.tier == tiers[0])
        else:
            conditions.append(CandidateCache.tier.in_(tiers))

    # State filter
    if state:
        states = [s.strip() for s in state.split(",")]
        if len(states) == 1:
            conditions.append(CandidateCache.state == states[0])
        else:
            conditions.append(CandidateCache.state.in_(states))

    # Date range filter (using last_activity_date from Zoho)
    if date_from:
        from datetime import datetime
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            conditions.append(CandidateCache.last_activity_date >= date_from_dt)
        except ValueError:
            pass
    if date_to:
        from datetime import datetime
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            # Add 1 day to include the end date fully
            from datetime import timedelta
            date_to_dt = date_to_dt + timedelta(days=1)
            conditions.append(CandidateCache.last_activity_date < date_to_dt)
        except ValueError:
            pass

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(CandidateCache.updated_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    candidates = result.scalars().all()

    return [
        CandidateResponse(
            id=c.id,
            zoho_id=c.zoho_id,
            zoho_module=c.zoho_module,
            full_name=c.full_name,
            email=c.email,
            phone=c.phone,
            stage=c.stage,
            assigned_client=c.assigned_client,
            tier=c.tier,
            languages=c.languages,
            last_activity_date=c.last_activity_date,
            last_communication_date=c.last_communication_date,
            days_in_stage=c.days_in_stage,
            is_unresponsive=c.is_unresponsive,
            has_pending_documents=c.has_pending_documents,
            needs_training=c.needs_training,
            zoho_url=get_crm_record_url(c.zoho_module, c.zoho_id)
        )
        for c in candidates
    ]


@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a single candidate by ID"""
    result = await db.execute(
        select(CandidateCache).where(CandidateCache.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return CandidateResponse(
        id=candidate.id,
        zoho_id=candidate.zoho_id,
        zoho_module=candidate.zoho_module,
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        stage=candidate.stage,
        assigned_client=candidate.assigned_client,
        tier=candidate.tier,
        languages=candidate.languages,
        last_activity_date=candidate.last_activity_date,
        last_communication_date=candidate.last_communication_date,
        days_in_stage=candidate.days_in_stage,
        is_unresponsive=candidate.is_unresponsive,
        has_pending_documents=candidate.has_pending_documents,
        needs_training=candidate.needs_training,
        zoho_url=get_crm_record_url(candidate.zoho_module, candidate.zoho_id)
    )


@router.get("/{candidate_id}/detail", response_model=CandidateDetailResponse)
async def get_candidate_detail(
    candidate_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get full candidate detail with all fields and related data"""
    result = await db.execute(
        select(CandidateCache).where(CandidateCache.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Fetch related notes
    notes_result = await db.execute(
        select(CandidateNote)
        .where(CandidateNote.candidate_id == candidate_id)
        .order_by(CandidateNote.created_at.desc())
    )
    notes = [
        CandidateNoteResponse(
            id=n.id,
            candidate_id=n.candidate_id,
            content=n.content,
            note_type=n.note_type,
            created_by=n.created_by,
            created_at=n.created_at,
            updated_at=n.updated_at
        )
        for n in notes_result.scalars().all()
    ]

    # Fetch related interviews (match by zoho_candidate_id since interviews are synced from Zoho)
    interviews_result = await db.execute(
        select(Interview)
        .where(Interview.zoho_candidate_id == candidate.zoho_id)
        .order_by(Interview.scheduled_date.desc())
    )
    interviews = [
        InterviewResponse(
            id=i.id,
            candidate_id=i.candidate_id,
            candidate_name=i.candidate_name,
            candidate_email=i.candidate_email,
            candidate_phone=i.candidate_phone,
            zoho_candidate_id=i.zoho_candidate_id,
            zoho_event_id=i.zoho_event_id,
            scheduled_date=i.scheduled_date,
            duration_minutes=i.duration_minutes,
            interview_type=i.interview_type,
            status=i.status,
            is_no_show=i.is_no_show,
            no_show_count=i.no_show_count,
            reschedule_count=i.reschedule_count,
            outcome=i.outcome,
            interviewer=i.interviewer,
            notes=i.notes,
            teams_meeting_link=i.teams_meeting_link,
            created_at=i.created_at
        )
        for i in interviews_result.scalars().all()
    ]

    # Fetch related tasks (match by zoho_candidate_id since tasks are synced from Zoho)
    tasks_result = await db.execute(
        select(Task)
        .where(Task.zoho_candidate_id == candidate.zoho_id)
        .order_by(Task.created_at.desc())
    )
    tasks = [
        TaskResponse(
            id=t.id,
            title=t.title,
            description=t.description,
            task_type=t.task_type,
            priority=t.priority,
            candidate_id=t.candidate_id,
            candidate_name=t.candidate_name,
            zoho_task_id=t.zoho_task_id,
            status=t.status,
            assigned_to=t.assigned_to,
            created_by=t.created_by,
            due_date=t.due_date,
            completed_at=t.completed_at,
            created_at=t.created_at
        )
        for t in tasks_result.scalars().all()
    ]

    return CandidateDetailResponse(
        id=candidate.id,
        zoho_id=candidate.zoho_id,
        zoho_module=candidate.zoho_module,
        zoho_url=get_crm_record_url(candidate.zoho_module, candidate.zoho_id),
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        mobile=candidate.mobile,
        whatsapp_number=candidate.whatsapp_number,
        city=candidate.city,
        state=candidate.state,
        country=candidate.country,
        service_location=candidate.service_location,
        candidate_status=candidate.candidate_status,
        stage=candidate.stage,
        tier=candidate.tier,
        language=candidate.language,
        languages=candidate.languages,
        candidate_owner=candidate.candidate_owner,
        recruitment_owner=candidate.recruitment_owner,
        assigned_client=candidate.assigned_client,
        agreed_rate=candidate.agreed_rate,
        language_assessment_passed=candidate.language_assessment_passed,
        language_assessment_grader=candidate.language_assessment_grader,
        language_assessment_date=candidate.language_assessment_date,
        bgv_passed=candidate.bgv_passed,
        system_specs_approved=candidate.system_specs_approved,
        offer_accepted=candidate.offer_accepted,
        offer_accepted_date=candidate.offer_accepted_date,
        training_accepted=candidate.training_accepted,
        training_status=candidate.training_status,
        training_start_date=candidate.training_start_date,
        training_end_date=candidate.training_end_date,
        alfa_one_onboarded=candidate.alfa_one_onboarded,
        next_followup=candidate.next_followup,
        followup_reason=candidate.followup_reason,
        recontact_date=candidate.recontact_date,
        last_activity_date=candidate.last_activity_date,
        last_communication_date=candidate.last_communication_date,
        days_in_stage=candidate.days_in_stage,
        stage_entered_date=candidate.stage_entered_date,
        is_unresponsive=candidate.is_unresponsive,
        has_pending_documents=candidate.has_pending_documents,
        needs_training=candidate.needs_training,
        disqualification_reason=candidate.disqualification_reason,
        candidate_source=candidate.candidate_source,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
        zoho_created_time=candidate.zoho_created_time,
        notes=notes,
        interviews=interviews,
        tasks=tasks
    )


# ============================================
# Candidate Notes
# ============================================

@router.get("/{candidate_id}/notes", response_model=List[CandidateNoteResponse])
async def get_candidate_notes(
    candidate_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get all notes for a candidate"""
    # Verify candidate exists
    candidate_result = await db.execute(
        select(CandidateCache.id).where(CandidateCache.id == candidate_id)
    )
    if not candidate_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidate not found")

    result = await db.execute(
        select(CandidateNote)
        .where(CandidateNote.candidate_id == candidate_id)
        .order_by(CandidateNote.created_at.desc())
    )
    notes = result.scalars().all()

    return [
        CandidateNoteResponse(
            id=n.id,
            candidate_id=n.candidate_id,
            content=n.content,
            note_type=n.note_type,
            created_by=n.created_by,
            created_at=n.created_at,
            updated_at=n.updated_at
        )
        for n in notes
    ]


@router.post("/{candidate_id}/notes", response_model=CandidateNoteResponse)
async def create_candidate_note(
    candidate_id: int,
    note: CandidateNoteCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new note for a candidate"""
    # Verify candidate exists
    candidate_result = await db.execute(
        select(CandidateCache.id).where(CandidateCache.id == candidate_id)
    )
    if not candidate_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidate not found")

    new_note = CandidateNote(
        candidate_id=candidate_id,
        content=note.content,
        note_type=note.note_type,
        created_by=note.created_by
    )
    db.add(new_note)
    await db.commit()
    await db.refresh(new_note)

    return CandidateNoteResponse(
        id=new_note.id,
        candidate_id=new_note.candidate_id,
        content=new_note.content,
        note_type=new_note.note_type,
        created_by=new_note.created_by,
        created_at=new_note.created_at,
        updated_at=new_note.updated_at
    )


@router.delete("/{candidate_id}/notes/{note_id}", response_model=SuccessResponse)
async def delete_candidate_note(
    candidate_id: int,
    note_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a candidate note"""
    result = await db.execute(
        select(CandidateNote).where(
            and_(
                CandidateNote.id == note_id,
                CandidateNote.candidate_id == candidate_id
            )
        )
    )
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    await db.delete(note)
    await db.commit()

    return SuccessResponse(message="Note deleted successfully")


@router.get("/zoho/{zoho_id}", response_model=CandidateResponse)
async def get_candidate_by_zoho_id(
    zoho_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a candidate by Zoho CRM ID"""
    result = await db.execute(
        select(CandidateCache).where(CandidateCache.zoho_id == zoho_id)
    )
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return CandidateResponse(
        id=candidate.id,
        zoho_id=candidate.zoho_id,
        zoho_module=candidate.zoho_module,
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        stage=candidate.stage,
        assigned_client=candidate.assigned_client,
        tier=candidate.tier,
        languages=candidate.languages,
        last_activity_date=candidate.last_activity_date,
        last_communication_date=candidate.last_communication_date,
        days_in_stage=candidate.days_in_stage,
        is_unresponsive=candidate.is_unresponsive,
        has_pending_documents=candidate.has_pending_documents,
        needs_training=candidate.needs_training,
        zoho_url=get_crm_record_url(candidate.zoho_module, candidate.zoho_id)
    )


# ============================================
# Stage Management
# ============================================

@router.post("/{candidate_id}/move-stage", response_model=CandidateResponse)
async def move_candidate_stage(
    candidate_id: int,
    new_stage: str = Query(..., description="New stage name"),
    db: AsyncSession = Depends(get_db)
):
    """Move candidate to a new pipeline stage"""
    valid_stages = [
        "New Candidate", "Screening", "Interview Scheduled", "Interview Completed",
        "Assessment", "Onboarding", "Active", "Inactive", "Rejected"
    ]

    if new_stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage. Must be one of: {', '.join(valid_stages)}"
        )

    result = await db.execute(
        select(CandidateCache).where(CandidateCache.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    old_stage = candidate.stage
    candidate.stage = new_stage
    candidate.stage_entered_date = datetime.utcnow()
    candidate.days_in_stage = 0
    candidate.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(candidate)

    return CandidateResponse(
        id=candidate.id,
        zoho_id=candidate.zoho_id,
        zoho_module=candidate.zoho_module,
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        stage=candidate.stage,
        assigned_client=candidate.assigned_client,
        tier=candidate.tier,
        languages=candidate.languages,
        last_activity_date=candidate.last_activity_date,
        last_communication_date=candidate.last_communication_date,
        days_in_stage=candidate.days_in_stage,
        is_unresponsive=candidate.is_unresponsive,
        has_pending_documents=candidate.has_pending_documents,
        needs_training=candidate.needs_training,
        zoho_url=get_crm_record_url(candidate.zoho_module, candidate.zoho_id)
    )


# ============================================
# Candidate Flags
# ============================================

@router.post("/{candidate_id}/flag-unresponsive", response_model=SuccessResponse)
async def flag_unresponsive(
    candidate_id: int,
    unresponsive: bool = Query(True),
    db: AsyncSession = Depends(get_db)
):
    """Flag/unflag candidate as unresponsive"""
    result = await db.execute(
        select(CandidateCache).where(CandidateCache.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate.is_unresponsive = unresponsive
    candidate.updated_at = datetime.utcnow()

    await db.commit()

    status = "flagged as unresponsive" if unresponsive else "marked as responsive"
    return SuccessResponse(message=f"Candidate {status}")


@router.post("/{candidate_id}/flag-pending-docs", response_model=SuccessResponse)
async def flag_pending_documents(
    candidate_id: int,
    pending: bool = Query(True),
    db: AsyncSession = Depends(get_db)
):
    """Flag/unflag candidate as having pending documents"""
    result = await db.execute(
        select(CandidateCache).where(CandidateCache.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate.has_pending_documents = pending
    candidate.updated_at = datetime.utcnow()

    await db.commit()

    status = "flagged with pending documents" if pending else "documents cleared"
    return SuccessResponse(message=f"Candidate {status}")
