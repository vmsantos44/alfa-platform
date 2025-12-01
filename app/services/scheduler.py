"""
Alfa Operations Platform - Background Task Scheduler
Handles scheduled tasks like auto-sync from Zoho CRM
"""
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from app.services.sync import SyncService


class SchedulerService:
    """
    Manages background scheduled tasks for the platform.
    """

    _instance: Optional["SchedulerService"] = None
    _scheduler: Optional[AsyncIOScheduler] = None
    _is_running: bool = False
    _sync_interval_minutes: int = 30
    _last_sync_result: Optional[Dict[str, Any]] = None
    _last_sync_time: Optional[datetime] = None
    _last_sync_error: Optional[str] = None
    _sync_in_progress: bool = False

    @classmethod
    def get_instance(cls) -> "SchedulerService":
        """Get singleton instance of scheduler service"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if SchedulerService._scheduler is None:
            SchedulerService._scheduler = AsyncIOScheduler()
            SchedulerService._scheduler.add_listener(
                self._job_listener,
                EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
            )

    def _job_listener(self, event):
        """Listen to job events for logging"""
        if event.exception:
            print(f"[Scheduler] Job {event.job_id} failed: {event.exception}")
            SchedulerService._last_sync_error = str(event.exception)
        else:
            print(f"[Scheduler] Job {event.job_id} completed successfully")

    async def _sync_job(self):
        """The actual sync job that runs on schedule - syncs candidates, interviews, tasks, notes, and emails"""
        if SchedulerService._sync_in_progress:
            print("[Scheduler] Sync already in progress, skipping...")
            return

        SchedulerService._sync_in_progress = True
        SchedulerService._last_sync_error = None

        try:
            print(f"[Scheduler] Starting auto-sync at {datetime.utcnow().isoformat()}")

            # Sync candidates
            print("[Scheduler] Syncing candidates...")
            candidate_result = await SyncService.sync_candidates_from_zoho()

            # Sync interviews
            print("[Scheduler] Syncing interviews...")
            interview_result = await SyncService.sync_interviews_from_zoho()

            # Sync tasks
            print("[Scheduler] Syncing tasks...")
            task_result = await SyncService.sync_tasks_from_zoho()

            # Sync notes (incremental - uses modified_since)
            print("[Scheduler] Syncing notes...")
            notes_result = await SyncService.sync_notes_from_zoho(full_sync=False)

            # Sync emails (last 30 days for active candidates)
            # This is more intensive, so we limit to recent emails only
            print("[Scheduler] Syncing emails...")
            try:
                email_result = await SyncService.sync_emails_from_zoho(days_back=30)
            except Exception as email_error:
                print(f"[Scheduler] Email sync failed (non-critical): {email_error}")
                email_result = {"emails_processed": 0, "emails_created": 0, "emails_updated": 0, "errors": 1}

            # Combine results
            result = {
                "candidates": candidate_result,
                "interviews": interview_result,
                "tasks": task_result,
                "notes": notes_result,
                "emails": email_result,
                "records_processed": (
                    candidate_result['records_processed'] +
                    interview_result['records_processed'] +
                    task_result['total_fetched'] +
                    notes_result['records_processed'] +
                    email_result.get('emails_processed', 0)
                ),
                "records_created": (
                    candidate_result['records_created'] +
                    interview_result['records_created'] +
                    task_result['created'] +
                    notes_result['records_created'] +
                    email_result.get('emails_created', 0)
                ),
                "records_updated": (
                    candidate_result['records_updated'] +
                    interview_result['records_updated'] +
                    task_result['updated'] +
                    notes_result['records_updated'] +
                    email_result.get('emails_updated', 0)
                ),
            }

            SchedulerService._last_sync_result = result
            SchedulerService._last_sync_time = datetime.utcnow()

            print(f"[Scheduler] Auto-sync completed: "
                  f"Candidates ({candidate_result['records_processed']}), "
                  f"Interviews ({interview_result['records_processed']}), "
                  f"Tasks ({task_result['total_fetched']}), "
                  f"Notes ({notes_result['records_processed']}), "
                  f"Emails ({email_result.get('emails_processed', 0)})")

        except Exception as e:
            SchedulerService._last_sync_error = str(e)
            print(f"[Scheduler] Auto-sync failed: {e}")
        finally:
            SchedulerService._sync_in_progress = False

    def start(self, interval_minutes: int = 30, run_immediately: bool = True):
        """
        Start the scheduler with the specified sync interval.

        Args:
            interval_minutes: How often to sync (default 30 minutes)
            run_immediately: Whether to run a sync immediately on startup
        """
        if SchedulerService._is_running:
            print("[Scheduler] Already running")
            return

        SchedulerService._sync_interval_minutes = interval_minutes

        # Add the sync job
        SchedulerService._scheduler.add_job(
            self._sync_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="auto_sync_zoho",
            name="Auto Sync from Zoho CRM",
            replace_existing=True
        )

        # Start the scheduler
        SchedulerService._scheduler.start()
        SchedulerService._is_running = True

        print(f"[Scheduler] Started with {interval_minutes}-minute sync interval")

        # Run immediately if requested
        if run_immediately:
            asyncio.create_task(self._sync_job())

    def stop(self):
        """Stop the scheduler"""
        if not SchedulerService._is_running:
            print("[Scheduler] Not running")
            return

        SchedulerService._scheduler.shutdown(wait=False)
        SchedulerService._is_running = False
        print("[Scheduler] Stopped")

    def pause(self):
        """Pause the scheduler (keeps jobs but doesn't run them)"""
        if SchedulerService._scheduler:
            SchedulerService._scheduler.pause()
            print("[Scheduler] Paused")

    def resume(self):
        """Resume the scheduler"""
        if SchedulerService._scheduler:
            SchedulerService._scheduler.resume()
            print("[Scheduler] Resumed")

    async def trigger_sync_now(self) -> Dict[str, Any]:
        """
        Manually trigger a sync immediately.

        Returns:
            Sync result or error message
        """
        if SchedulerService._sync_in_progress:
            return {"error": "Sync already in progress"}

        await self._sync_job()

        if SchedulerService._last_sync_error:
            return {"error": SchedulerService._last_sync_error}

        return SchedulerService._last_sync_result or {"message": "Sync completed"}

    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status"""
        next_run = None
        if SchedulerService._scheduler and SchedulerService._is_running:
            job = SchedulerService._scheduler.get_job("auto_sync_zoho")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

        return {
            "is_running": SchedulerService._is_running,
            "sync_interval_minutes": SchedulerService._sync_interval_minutes,
            "sync_in_progress": SchedulerService._sync_in_progress,
            "last_sync_time": SchedulerService._last_sync_time.isoformat() if SchedulerService._last_sync_time else None,
            "last_sync_result": SchedulerService._last_sync_result,
            "last_sync_error": SchedulerService._last_sync_error,
            "next_sync_time": next_run
        }

    def update_interval(self, interval_minutes: int):
        """Update the sync interval"""
        if not SchedulerService._is_running:
            SchedulerService._sync_interval_minutes = interval_minutes
            return

        # Reschedule the job with new interval
        SchedulerService._scheduler.reschedule_job(
            "auto_sync_zoho",
            trigger=IntervalTrigger(minutes=interval_minutes)
        )
        SchedulerService._sync_interval_minutes = interval_minutes
        print(f"[Scheduler] Updated sync interval to {interval_minutes} minutes")


# Convenience functions for use in main.py
def get_scheduler() -> SchedulerService:
    """Get the scheduler service instance"""
    return SchedulerService.get_instance()


def start_scheduler(interval_minutes: int = 30, run_immediately: bool = True):
    """Start the scheduler"""
    scheduler = get_scheduler()
    scheduler.start(interval_minutes=interval_minutes, run_immediately=run_immediately)


def stop_scheduler():
    """Stop the scheduler"""
    scheduler = get_scheduler()
    scheduler.stop()
