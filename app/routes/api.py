"""API router - CRM and integration endpoints
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from datetime import datetime
from math import ceil

router = APIRouter()

# -----------------------------------------------------------------------------
# In-memory scheduler status (placeholder for local testing)
# -----------------------------------------------------------------------------
scheduler_status = {
    "is_running": False,
    "last_sync": None,
    "next_sync": None,
    "interval_minutes": 30,
    "total_syncs": 0,
}


@router.get("/")
async def api_root():
    """API endpoint root"""
    return {
        "service": "Alfa Platform API",
        "version": "2.0.0",
        "endpoints": [
            "/api/candidates/",
            "/api/candidates/filter-options",
            "/api/candidates/{id}",
            "/api/sync/scheduler/status",
            "/api/sync/scheduler/start",
            "/api/sync/scheduler/stop",
            "/api/sync/scheduler/trigger",
            "/api/dashboard/analytics/recent-activity",
            "/api/dashboard/alerts",
            "/api/alerts/",
            "/api/tasks/action-required",
        ],
    }


# =============================================================================
# CANDIDATES API (with pagination support)
# =============================================================================

@router.get("/candidates/")
async def list_candidates(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(default=50, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="days_in_stage", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort order: asc or desc"),
    stage: Optional[str] = Query(default=None, description="Filter by stage(s), comma-separated"),
    search: Optional[str] = Query(default=None, description="Search by name or email"),
    language: Optional[str] = Query(default=None, description="Filter by language(s), comma-separated"),
    owner: Optional[str] = Query(default=None, description="Filter by recruitment owner(s), comma-separated"),
    tier: Optional[str] = Query(default=None, description="Filter by tier(s), comma-separated"),
    days_min: Optional[int] = Query(default=None, description="Minimum days in stage"),
    days_max: Optional[int] = Query(default=None, description="Maximum days in stage"),
    unresponsive: Optional[bool] = Query(default=None, description="Filter unresponsive candidates"),
    pending_docs: Optional[bool] = Query(default=None, description="Filter candidates with pending docs"),
):
    """
    Return paginated candidate list.
    
    Supports filtering, sorting, and pagination.
    """
    # Calculate offset for database query
    offset = (page - 1) * per_page
    
    # TODO: Replace with actual database query
    # For now, return empty list with pagination structure
    total = 0  # Would come from COUNT(*) query
    total_pages = ceil(total / per_page) if total > 0 else 1
    
    return {
        "success": True,
        "candidates": [],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "offset": offset,
        },
        "sort": {
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
        "filters": {
            "stage": stage,
            "search": search,
            "language": language,
            "owner": owner,
            "tier": tier,
            "days_min": days_min,
            "days_max": days_max,
            "unresponsive": unresponsive,
            "pending_docs": pending_docs,
        },
    }


@router.get("/candidates/filter-options")
async def get_filter_options():
    """Provide static filter options used by the UI."""
    return {
        "stages": [
            "New Lead",
            "Contacted",
            "Qualified",
            "Interview Scheduled",
            "Interview Completed",
            "Training Required (Client/Tier)",
            "Credentials Ordered (Interpreter)",
            "Active",
            "On Hold",
            "Not Interested",
            "Disqualified",
        ],
        "tiers": ["Tier 1", "Tier 2", "Tier 3"],
        "clients": ["Cloudbreak", "Voyce", "Martti", "AMN", "Other"],
        "languages": [
            "Spanish",
            "Mandarin",
            "Cantonese",
            "Vietnamese",
            "Korean",
            "Arabic",
            "Russian",
            "French",
            "Portuguese",
            "Other",
        ],
    }


@router.get("/candidates/pipeline")
async def get_pipeline(
    include_candidates: bool = Query(default=True, description="Include candidate data in response"),
    candidates_per_stage: int = Query(default=20, ge=1, le=100, description="Max candidates per stage"),
    stage: Optional[str] = Query(default=None, description="Filter to specific stage(s), comma-separated"),
    search: Optional[str] = Query(default=None, description="Search filter"),
    language: Optional[str] = Query(default=None, description="Language filter"),
    owner: Optional[str] = Query(default=None, description="Owner filter"),
    tier: Optional[str] = Query(default=None, description="Tier filter"),
):
    """
    Return pipeline data grouped by stage for Kanban view.
    
    Each stage includes:
    - stage name
    - total count of candidates in that stage
    - list of candidates (limited by candidates_per_stage)
    - has_more flag indicating if there are more candidates to load
    """
    # Define pipeline stages in order
    pipeline_stages = [
        "New Candidate",
        "Screening",
        "Interview Scheduled",
        "Interview Completed",
        "Assessment",
        "Onboarding",
        "Active",
        "Inactive",
        "Rejected",
    ]
    
    # Filter stages if specified
    if stage:
        requested_stages = [s.strip() for s in stage.split(",")]
        pipeline_stages = [s for s in pipeline_stages if s in requested_stages]
    
    # TODO: Replace with actual database queries
    # For now, return empty pipeline structure
    pipeline = []
    for stage_name in pipeline_stages:
        pipeline.append({
            "stage": stage_name,
            "count": 0,  # Total candidates in this stage
            "candidates": [] if include_candidates else None,
            "has_more": False,  # Whether there are more candidates to load
            "loaded": 0,  # Number of candidates currently loaded
        })
    
    return pipeline


@router.get("/candidates/pipeline/{stage}/load-more")
async def load_more_pipeline_candidates(
    stage: str,
    offset: int = Query(default=0, ge=0, description="Number of candidates already loaded"),
    limit: int = Query(default=20, ge=1, le=50, description="Number of candidates to load"),
    search: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    owner: Optional[str] = Query(default=None),
    tier: Optional[str] = Query(default=None),
):
    """
    Load more candidates for a specific pipeline stage.
    
    Used for infinite scroll / load more functionality in Kanban view.
    """
    # TODO: Replace with actual database query
    # Would query: SELECT * FROM candidates WHERE stage = :stage LIMIT :limit OFFSET :offset
    
    return {
        "stage": stage,
        "candidates": [],
        "offset": offset,
        "limit": limit,
        "has_more": False,
        "total_in_stage": 0,
    }


@router.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: str):
    """Return a minimal candidate profile (placeholder)."""
    # For now, return a basic structure so the UI renders
    if not candidate_id:
        raise HTTPException(status_code=400, detail="candidate_id is required")
    return {
        "success": True,
        "module": "Contacts",
        "record_id": candidate_id,
        "record": {"id": candidate_id, "Full_Name": "Unknown", "Email": ""},
        "notes": {"count": 0, "items": []},
        "communications": {"count": 0, "emails": [], "calls": [], "tasks": [], "events": []},
        "attachments": {"count": 0, "items": []},
    }


# =============================================================================
# SYNC SCHEDULER API
# =============================================================================

@router.get("/sync/scheduler/status")
async def get_scheduler_status():
    """Get current scheduler status."""
    return {"success": True, "status": scheduler_status}


@router.post("/sync/scheduler/start")
async def start_scheduler():
    """Start the sync scheduler (placeholder)."""
    global scheduler_status
    scheduler_status["is_running"] = True
    scheduler_status["next_sync"] = datetime.now().isoformat()
    return {"success": True, "message": "Scheduler started", "status": scheduler_status}


@router.post("/sync/scheduler/stop")
async def stop_scheduler():
    """Stop the sync scheduler (placeholder)."""
    global scheduler_status
    scheduler_status["is_running"] = False
    scheduler_status["next_sync"] = None
    return {"success": True, "message": "Scheduler stopped", "status": scheduler_status}


@router.post("/sync/scheduler/trigger")
async def trigger_sync():
    """Manually trigger a sync (placeholder)."""
    global scheduler_status
    scheduler_status["last_sync"] = datetime.now().isoformat()
    scheduler_status["total_syncs"] += 1
    return {
        "success": True,
        "message": "Sync triggered successfully",
        "sync_time": scheduler_status["last_sync"],
        "total_syncs": scheduler_status["total_syncs"],
    }


@router.put("/sync/scheduler/interval")
async def update_scheduler_interval(interval_minutes: int = Query(..., ge=1, le=1440)):
    """Update the scheduler interval (placeholder)."""
    global scheduler_status
    scheduler_status["interval_minutes"] = interval_minutes
    return {
        "success": True,
        "message": f"Interval updated to {interval_minutes} minutes",
        "status": scheduler_status,
    }


# =============================================================================
# DASHBOARD & ALERTS API (placeholders)
# =============================================================================

@router.get("/dashboard/analytics/recent-activity")
async def get_recent_activity(limit: int = Query(default=50, le=100)):
    """Return recent activity (placeholder)."""
    return {"success": True, "activities": [], "total": 0, "limit": limit}


@router.get("/dashboard/alerts")
async def get_dashboard_alerts(limit: int = Query(default=5, le=20)):
    """Return dashboard alerts (placeholder)."""
    return {"success": True, "alerts": [], "total": 0, "limit": limit}


@router.get("/alerts/")
async def list_alerts(limit: int = Query(default=10, le=50)):
    """Return alerts list (placeholder)."""
    return {"success": True, "alerts": [], "total": 0, "limit": limit}


@router.get("/tasks/action-required")
async def get_action_required_tasks(limit: int = Query(default=100, le=200)):
    """Return tasks requiring action (placeholder)."""
    return {"success": True, "tasks": [], "total": 0, "limit": limit}
