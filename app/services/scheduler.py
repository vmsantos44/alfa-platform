"""
Auto-sync scheduler service
Handles automatic synchronization from Zoho CRM at configurable intervals
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
import sqlite3
import json
import os

logger = logging.getLogger(__name__)

# Settings file path for persistence
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'scheduler_settings.json')


class SchedulerService:
    """Manages automatic sync scheduling"""
    
    _scheduler: Optional[AsyncIOScheduler] = None
    _is_running: bool = False
    _sync_in_progress: bool = False
    _sync_interval_minutes: int = 30
    _last_sync_result: Optional[Dict[str, Any]] = None
    _last_sync_time: Optional[datetime] = None
    _last_sync_error: Optional[str] = None
    
    @classmethod
    def _load_settings(cls):
        """Load settings from file"""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    cls._sync_interval_minutes = settings.get('sync_interval_minutes', 30)
                    logger.info(f"[Scheduler] Loaded interval setting: {cls._sync_interval_minutes} minutes")
        except Exception as e:
            logger.warning(f"[Scheduler] Could not load settings: {e}")
    
    @classmethod
    def _save_settings(cls):
        """Save settings to file"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, 'w') as f:
                json.dump({'sync_interval_minutes': cls._sync_interval_minutes}, f)
        except Exception as e:
            logger.warning(f"[Scheduler] Could not save settings: {e}")
    
    @classmethod
    def _load_last_sync_from_db(cls):
        """Load last sync info from database"""
        try:
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'alfa_platform.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                # Get the most recent completed sync
                cursor.execute("""
                    SELECT sync_type, completed_at, records_processed, records_created, records_updated, errors 
                    FROM sync_logs 
                    WHERE status = 'completed' 
                    ORDER BY completed_at DESC 
                    LIMIT 1
                """)
                row = cursor.fetchone()
                if row:
                    cls._last_sync_time = datetime.fromisoformat(row[1]) if row[1] else None
                    # Get aggregate stats from recent syncs
                    cursor.execute("""
                        SELECT 
                            SUM(records_processed) as total_processed,
                            SUM(records_created) as total_created,
                            SUM(records_updated) as total_updated,
                            SUM(errors) as total_errors,
                            MAX(completed_at) as last_completed
                        FROM sync_logs 
                        WHERE status = 'completed' 
                        AND completed_at > datetime('now', '-1 hour')
                    """)
                    stats = cursor.fetchone()
                    if stats and stats[0]:
                        cls._last_sync_result = {
                            'candidates': {
                                'processed': stats[0] or 0,
                                'created': stats[1] or 0,
                                'updated': stats[2] or 0,
                                'errors': stats[3] or 0
                            },
                            'total_processed': stats[0] or 0,
                            'total_created': stats[1] or 0,
                            'total_updated': stats[2] or 0,
                            'total_errors': stats[3] or 0
                        }
                        logger.info(f"[Scheduler] Loaded last sync from DB: {stats[0]} processed at {stats[4]}")
                conn.close()
        except Exception as e:
            logger.warning(f"[Scheduler] Could not load last sync from DB: {e}")

    def __init__(self):
        pass

    @classmethod
    async def start(cls, interval_minutes: int = None, run_immediately: bool = True):
        """Start the scheduler with specified interval"""
        # Load persisted settings
        cls._load_settings()
        cls._load_last_sync_from_db()
        
        if interval_minutes:
            cls._sync_interval_minutes = interval_minutes
            cls._save_settings()
        
        if cls._scheduler is not None:
            logger.warning("[Scheduler] Already running")
            return
        
        cls._scheduler = AsyncIOScheduler()
        cls._scheduler.add_listener(cls._job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        
        cls._scheduler.add_job(
            cls._sync_job,
            IntervalTrigger(minutes=cls._sync_interval_minutes),
            id='auto_sync_zoho',
            name='Auto Sync from Zoho CRM',
            replace_existing=True
        )
        
        cls._scheduler.start()
        cls._is_running = True
        logger.info(f"[Scheduler] Started with {cls._sync_interval_minutes}-minute sync interval")
        
        # Run initial sync if requested
        if run_immediately:
            asyncio.create_task(cls._sync_job())

    @classmethod
    async def stop(cls):
        """Stop the scheduler"""
        if cls._scheduler is not None:
            cls._scheduler.shutdown(wait=False)
            cls._scheduler = None
            cls._is_running = False
            logger.info("[Scheduler] Stopped")

    @classmethod
    async def pause(cls):
        """Pause the scheduler (keeps schedule but doesn't run)"""
        if cls._scheduler:
            cls._scheduler.pause()
            logger.info("[Scheduler] Paused")

    @classmethod
    async def resume(cls):
        """Resume the scheduler"""
        if cls._scheduler:
            cls._scheduler.resume()
            logger.info("[Scheduler] Resumed")

    @classmethod
    async def _sync_job(cls):
        """Execute the sync job"""
        if cls._sync_in_progress:
            logger.warning("[Scheduler] Sync already in progress, skipping")
            return
        
        cls._sync_in_progress = True
        cls._last_sync_time = datetime.utcnow()
        
        try:
            from app.services.sync import SyncService
            
            result = {
                'candidates': None,
                'interviews': None,
                'tasks': None,
                'notes': None,
                'emails': None,
                'total_processed': 0,
                'total_created': 0,
                'total_updated': 0,
                'total_errors': 0
            }
            
            # Sync candidates
            logger.info("[Scheduler] Syncing candidates...")
            candidates_result = await SyncService.sync_candidates()
            result['candidates'] = candidates_result
            result['total_processed'] += candidates_result.get('records_processed', 0)
            result['total_created'] += candidates_result.get('records_created', 0)
            result['total_updated'] += candidates_result.get('records_updated', 0)
            result['total_errors'] += candidates_result.get('errors', 0)
            
            # Sync interviews
            logger.info("[Scheduler] Syncing interviews...")
            interviews_result = await SyncService.sync_interviews()
            result['interviews'] = interviews_result
            result['total_processed'] += interviews_result.get('records_processed', 0)
            result['total_created'] += interviews_result.get('records_created', 0)
            result['total_updated'] += interviews_result.get('records_updated', 0)
            result['total_errors'] += interviews_result.get('errors', 0)
            
            # Sync tasks
            logger.info("[Scheduler] Syncing tasks...")
            tasks_result = await SyncService.sync_tasks()
            result['tasks'] = tasks_result
            result['total_processed'] += tasks_result.get('records_processed', 0)
            result['total_created'] += tasks_result.get('records_created', 0)
            result['total_updated'] += tasks_result.get('records_updated', 0)
            result['total_errors'] += tasks_result.get('errors', 0)
            
            # Sync notes (incremental)
            logger.info("[Scheduler] Syncing notes...")
            notes_result = await SyncService.sync_crm_notes(incremental=True)
            result['notes'] = notes_result
            result['total_processed'] += notes_result.get('records_processed', 0)
            result['total_created'] += notes_result.get('records_created', 0)
            result['total_updated'] += notes_result.get('records_updated', 0)
            result['total_errors'] += notes_result.get('errors', 0)
            
            # Sync emails (last 30 days)
            try:
                logger.info("[Scheduler] Syncing emails...")
                emails_result = await SyncService.sync_emails(days_back=30)
                result['emails'] = emails_result
                result['total_processed'] += emails_result.get('records_processed', 0)
                result['total_created'] += emails_result.get('records_created', 0)
                result['total_updated'] += emails_result.get('records_updated', 0)
                result['total_errors'] += emails_result.get('errors', 0)
            except Exception as e:
                logger.warning(f"[Scheduler] Email sync failed (non-critical): {e}")
                result['emails'] = {'error': str(e)}
            
            cls._last_sync_result = result
            cls._last_sync_error = None
            logger.info(f"[Scheduler] Sync completed: {result['total_processed']} processed, {result['total_created']} created, {result['total_updated']} updated")
            
        except Exception as e:
            cls._last_sync_error = str(e)
            logger.error(f"[Scheduler] Sync failed: {e}")
            raise
        finally:
            cls._sync_in_progress = False

    @classmethod
    def _job_listener(cls, event):
        """Listen for job events"""
        if event.exception:
            cls._last_sync_error = str(event.exception)
            logger.error(f"[Scheduler] Job failed: {event.exception}")
        else:
            logger.info("[Scheduler] Job completed successfully")

    @classmethod
    async def trigger_sync_now(cls) -> Dict[str, Any]:
        """Trigger an immediate sync"""
        if cls._sync_in_progress:
            return {"error": "Sync already in progress"}
        
        try:
            await cls._sync_job()
            return cls._last_sync_result or {"message": "Sync completed"}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def get_last_sync_result(cls) -> Dict[str, Any]:
        """Get the result of the last sync"""
        # If no result in memory, try loading from DB
        if cls._last_sync_result is None:
            cls._load_last_sync_from_db()
        return cls._last_sync_result or {"message": "Sync completed"}

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Get current scheduler status"""
        # If no result in memory, try loading from DB
        if cls._last_sync_result is None:
            cls._load_last_sync_from_db()
            
        next_run = None
        if cls._scheduler:
            job = cls._scheduler.get_job('auto_sync_zoho')
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()
        
        return {
            "is_running": cls._is_running,
            "sync_interval_minutes": cls._sync_interval_minutes,
            "sync_in_progress": cls._sync_in_progress,
            "last_sync_time": cls._last_sync_time.isoformat() if cls._last_sync_time else None,
            "last_sync_result": cls._last_sync_result,
            "last_sync_error": cls._last_sync_error,
            "next_sync_time": next_run
        }

    @classmethod
    async def update_interval(cls, interval_minutes: int):
        """Update the sync interval"""
        cls._sync_interval_minutes = interval_minutes
        cls._save_settings()  # Persist the setting
        
        if cls._scheduler:
            cls._scheduler.reschedule_job(
                'auto_sync_zoho',
                trigger=IntervalTrigger(minutes=interval_minutes)
            )
            logger.info(f"[Scheduler] Interval updated to {interval_minutes} minutes")
    
    @classmethod
    def set_interval(cls, interval_minutes: int):
        """Set the interval (for startup)"""
        cls._sync_interval_minutes = interval_minutes
        cls._save_settings()


# Convenience functions
def get_scheduler() -> SchedulerService:
    return SchedulerService()


async def start_scheduler(interval_minutes: int = 30, run_immediately: bool = True):
    await SchedulerService.start(interval_minutes, run_immediately)


async def stop_scheduler():
    await SchedulerService.stop()
