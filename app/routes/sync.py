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
