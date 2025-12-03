"""
Data Synchronization API endpoints
Sync data between Zoho CRM and local database
"""
from fastapi import APIRouter, HTTPException, Query, Path
from app.services.sync import SyncService
from app.services.scheduler import SchedulerService, SYNC_CATEGORIES
from app.models.schemas import SyncStatus, SuccessResponse

router = APIRouter()


# ============================================
# Scheduler Control Endpoints
# ============================================

@router.get("/scheduler/status")
async def get_scheduler_status():
    """Get the current status of the auto-sync scheduler with per-category info"""
    return SchedulerService.get_status()


@router.post("/scheduler/start")
async def start_auto_sync():
    """Start the auto-sync scheduler"""
    await SchedulerService.start(run_immediately=False)
    return {"message": "Scheduler started", **SchedulerService.get_status()}


@router.post("/scheduler/stop")
async def stop_auto_sync():
    """Stop the auto-sync scheduler"""
    await SchedulerService.stop()
    return {"message": "Scheduler stopped", **SchedulerService.get_status()}


@router.post("/scheduler/trigger")
async def trigger_sync_now(category: str = Query(None, description="Category to sync (or all if not specified)")):
    """Manually trigger a sync immediately"""
    result = await SchedulerService.trigger_sync(category)
    return result


@router.put("/scheduler/interval/{category}")
async def update_category_interval(
    category: str = Path(..., description="Sync category (candidates, interviews, tasks, notes, emails)"),
    interval_minutes: int = Query(..., ge=1, le=1440, description="Interval in minutes (1-1440)")
):
    """Update the sync interval for a specific category"""
    if category not in SYNC_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}. Valid: {list(SYNC_CATEGORIES.keys())}")
    
    await SchedulerService.update_interval(category, interval_minutes)
    status = SchedulerService.get_status()
    return {
        "message": f"{category} interval updated to {interval_minutes} minutes",
        "category": status['categories'].get(category)
    }


# ============================================
# Manual Sync Endpoints
# ============================================

@router.post("/candidates")
async def sync_candidates(
    limit: int = Query(None, description="Max records to sync")
):
    """Sync candidates from Zoho CRM"""
    result = await SyncService.sync_candidates_from_zoho()
    return result


@router.post("/interviews")
async def sync_interviews(
    limit: int = Query(500, description="Max records to sync")
):
    """Sync interviews from Zoho CRM"""
    result = await SyncService.sync_interviews_from_zoho()
    return result


@router.post("/tasks")
async def sync_tasks(
    limit: int = Query(500, description="Max records to sync")
):
    """Sync tasks from Zoho CRM"""
    result = await SyncService.sync_tasks_from_zoho()
    return result


@router.post("/notes")
async def sync_notes(
    incremental: bool = Query(True, description="Only sync notes modified since last sync"),
    limit: int = Query(None, description="Max records to sync")
):
    """Sync notes from Zoho CRM"""
    result = await SyncService.sync_notes_from_zoho(full_sync=not incremental)
    return result


@router.post("/emails")
async def sync_emails(
    days_back: int = Query(30, description="Number of days to look back for emails")
):
    """Sync emails from Zoho Mail"""
    try:
        result = await SyncService.sync_emails_from_zoho(days_back=days_back)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_sync_status():
    """Get the last sync status for all categories"""
    return SchedulerService.get_status()


# ============================================
# Debug Endpoints
# ============================================

@router.post("/sample-data")
async def generate_sample_data():
    """Generate sample data for testing"""
    # This would generate test data - kept for compatibility
    return {"message": "Sample data generation not implemented"}


@router.get("/debug-zoho")
async def debug_zoho_connection():
    """Test Zoho CRM API connection"""
    from app.integrations.zoho.crm import ZohoAPI
    try:
        api = ZohoAPI()
        # Just check if we can initialize the API (token refresh works)
        if api.access_token:
            return {
                "status": "connected",
                "message": "Zoho API credentials valid"
            }
        else:
            return {
                "status": "error",
                "error": "No access token"
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
