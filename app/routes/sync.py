"""
Data Synchronization API endpoints
Sync data between Zoho CRM and local database
"""
from fastapi import APIRouter, HTTPException, Query
from app.services.sync import SyncService
from app.services.scheduler import get_scheduler
from app.models.schemas import SyncStatus, SuccessResponse

router = APIRouter()


# ============================================
# Scheduler Control Endpoints
# ============================================

@router.get("/scheduler/status")
async def get_scheduler_status():
    """Get the current status of the auto-sync scheduler"""
    scheduler = get_scheduler()
    return scheduler.get_status()


@router.post("/scheduler/start")
async def start_auto_sync(
    interval_minutes: int = Query(30, ge=5, le=1440, description="Sync interval in minutes (5-1440)")
):
    """Start the auto-sync scheduler"""
    scheduler = get_scheduler()
    status = scheduler.get_status()

    if status["is_running"]:
        return {"message": "Scheduler already running", **status}

    scheduler.start(interval_minutes=interval_minutes, run_immediately=False)
    return {"message": f"Scheduler started with {interval_minutes}-minute interval", **scheduler.get_status()}


@router.post("/scheduler/stop")
async def stop_auto_sync():
    """Stop the auto-sync scheduler"""
    scheduler = get_scheduler()
    status = scheduler.get_status()

    if not status["is_running"]:
        return {"message": "Scheduler not running", **status}

    scheduler.stop()
    return {"message": "Scheduler stopped", **scheduler.get_status()}


@router.post("/scheduler/pause")
async def pause_auto_sync():
    """Pause the auto-sync scheduler (keeps schedule but doesn't run)"""
    scheduler = get_scheduler()
    scheduler.pause()
    return {"message": "Scheduler paused", **scheduler.get_status()}


@router.post("/scheduler/resume")
async def resume_auto_sync():
    """Resume the auto-sync scheduler"""
    scheduler = get_scheduler()
    scheduler.resume()
    return {"message": "Scheduler resumed", **scheduler.get_status()}


@router.post("/scheduler/trigger")
async def trigger_sync_now():
    """Manually trigger a sync immediately"""
    scheduler = get_scheduler()
    result = await scheduler.trigger_sync_now()
    return result


@router.put("/scheduler/interval")
async def update_sync_interval(
    interval_minutes: int = Query(..., ge=5, le=1440, description="New sync interval in minutes (5-1440)")
):
    """Update the sync interval"""
    scheduler = get_scheduler()
    scheduler.update_interval(interval_minutes)
    return {"message": f"Interval updated to {interval_minutes} minutes", **scheduler.get_status()}


# ============================================
# Manual Sync Endpoints
# ============================================


@router.post("/candidates")
async def sync_candidates():
    """
    Sync candidates from Zoho CRM Leads module to local database.
    Maps Zoho CRM fields to local pipeline stages.
    """
    try:
        stats = await SyncService.sync_candidates_from_zoho()
        return {
            "success": True,
            "message": "Sync completed",
            **stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.get("/status")
async def get_sync_status():
    """Get the status of the last sync"""
    last_sync = await SyncService.get_last_sync()
    return {
        "last_sync": last_sync.isoformat() if last_sync else None,
        "status": "ok" if last_sync else "never_synced"
    }


@router.post("/sample-data")
async def create_sample_data():
    """
    Create sample data for testing.
    Use this if you don't have Zoho CRM connected yet.
    """
    try:
        result = await SyncService.create_sample_data()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create sample data: {str(e)}")


@router.get("/debug-zoho")
async def debug_zoho_data():
    """
    Debug endpoint to see raw Zoho CRM data for a few leads.
    Shows what fields Zoho is actually returning.
    """
    from app.integrations.zoho.crm import ZohoCRM

    try:
        crm = ZohoCRM()
        response = await crm.get_records(
            module="Leads",
            page=1,
            per_page=5,
            fields=[
                "id", "First_Name", "Last_Name", "Email",
                "Candidate_Status", "Tier_Level", "Language"
            ]
        )

        records = response.get("data", [])
        return {
            "count": len(records),
            "sample_records": records,
            "info": response.get("info", {})
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")
