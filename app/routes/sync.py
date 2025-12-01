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


@router.post("/interviews")
async def sync_interviews():
    """
    Sync interviews from Zoho CRM Events module to local database.
    Fetches events that contain 'interview' in the title and maps them to Interview records.
    """
    try:
        stats = await SyncService.sync_interviews_from_zoho()
        return {
            "success": True,
            "message": "Interview sync completed",
            **stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Interview sync failed: {str(e)}")


@router.get("/status")
async def get_sync_status():
    """Get the status of the last sync for both candidates and interviews"""
    last_candidate_sync = await SyncService.get_last_sync()
    last_interview_sync = await SyncService.get_last_interview_sync()
    return {
        "candidates": {
            "last_sync": last_candidate_sync.isoformat() if last_candidate_sync else None,
            "status": "ok" if last_candidate_sync else "never_synced"
        },
        "interviews": {
            "last_sync": last_interview_sync.isoformat() if last_interview_sync else None,
            "status": "ok" if last_interview_sync else "never_synced"
        }
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


@router.get("/debug-events")
async def debug_zoho_events():
    """
    Debug endpoint to see raw Zoho CRM Events data.
    Shows what interview events Zoho is returning.
    """
    from app.integrations.zoho.crm import ZohoCRM

    try:
        crm = ZohoCRM()
        response = await crm.get_records(
            module="Events",
            page=1,
            per_page=20,
            fields=[
                "id", "Event_Title", "Subject", "Start_DateTime", "End_DateTime",
                "What_Id", "$se_module", "Owner", "Participants",
                "Check_In_Status", "Description", "Created_Time", "Modified_Time"
            ]
        )

        records = response.get("data", [])

        # Identify interview events
        interview_events = []
        other_events = []
        interview_keywords = ["interview", "screening", "auto interview", "candidate call",
                             "hiring call", "recruitment call", "phone screen"]

        for record in records:
            title = record.get("Event_Title", "") or record.get("Subject", "") or ""
            title_lower = title.lower()
            is_interview = any(kw in title_lower for kw in interview_keywords)
            if is_interview:
                interview_events.append(record)
            else:
                other_events.append(record)

        return {
            "total_events": len(records),
            "interview_events": len(interview_events),
            "other_events": len(other_events),
            "interview_samples": interview_events[:5],
            "other_samples": other_events[:5],
            "info": response.get("info", {})
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug events failed: {str(e)}")


@router.get("/debug-bookings")
async def debug_zoho_bookings():
    """
    Debug endpoint to see raw Zoho Bookings data.
    Shows actual booking appointments with their status (COMPLETED, NO_SHOW, etc.)
    """
    from app.integrations.zoho.bookings import get_zoho_bookings
    from datetime import datetime, timedelta
    import httpx

    try:
        bookings_api = await get_zoho_bookings()

        # Check configuration
        config_info = {
            "is_configured": bookings_api.is_configured(),
            "has_dedicated_credentials": bookings_api.has_dedicated_credentials(),
            "using_fallback": not bookings_api.has_dedicated_credentials() and bookings_api.is_configured()
        }

        if not bookings_api.is_configured():
            return {
                "error": "Zoho Bookings not configured",
                "config_info": config_info,
                "instructions": "Add ZOHO_BOOKINGS_CLIENT_ID, ZOHO_BOOKINGS_CLIENT_SECRET, and ZOHO_BOOKINGS_REFRESH_TOKEN to .env"
            }

        # Try fetching with NO parameters (should return today's appointments per docs)
        headers = await bookings_api._get_headers()

        raw_response = await bookings_api.client.post(
            "https://www.zohoapis.com/bookings/v1/json/fetchappointment",
            headers=headers,
            data={}  # Form-data: Empty = today's appointments
        )

        raw_data = raw_response.json() if raw_response.status_code == 200 else {"error": raw_response.text}

        # Also try with date range
        from_date = datetime.utcnow() - timedelta(days=30)
        to_date = datetime.utcnow() + timedelta(days=30)

        result = await bookings_api.fetch_appointments(
            from_date=from_date,
            to_date=to_date,
            page=1,
            per_page=50
        )

        appointments = result.get("appointments", [])

        # Count by status
        status_counts = {}
        for booking in appointments:
            status = booking.get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "config_info": config_info,
            "total_bookings": len(appointments),
            "status_counts": status_counts,
            "sample_bookings": appointments[:5],
            "next_page_available": result.get("next_page_available", False),
            "raw_today_response": raw_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug bookings failed: {str(e)}")
