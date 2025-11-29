"""
Data Synchronization API endpoints
Sync data between Zoho CRM and local database
"""
from fastapi import APIRouter, HTTPException
from app.services.sync import SyncService
from app.models.schemas import SyncStatus, SuccessResponse

router = APIRouter()


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
