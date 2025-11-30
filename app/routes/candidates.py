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
from app.models.database_models import CandidateCache, ActionAlert, Interview, Task
from app.models.schemas import (
    CandidateResponse,
    CandidateSummary,
    PipelineStage,
    SuccessResponse
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
                    has_pending_documents=c.has_pending_documents
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
    stage: Optional[str] = Query(None, description="Filter by stage"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    unresponsive: Optional[bool] = Query(None, description="Filter unresponsive"),
    pending_docs: Optional[bool] = Query(None, description="Filter pending documents"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """List candidates with filters"""
    query = select(CandidateCache)

    # Apply filters
    conditions = []
    if stage:
        conditions.append(CandidateCache.stage == stage)
    if search:
        search_term = f"%{search}%"
        conditions.append(
            or_(
                CandidateCache.full_name.ilike(search_term),
                CandidateCache.email.ilike(search_term)
            )
        )
    if unresponsive is not None:
        conditions.append(CandidateCache.is_unresponsive == unresponsive)
    if pending_docs is not None:
        conditions.append(CandidateCache.has_pending_documents == pending_docs)

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
