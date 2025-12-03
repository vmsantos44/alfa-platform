"""
Auto-sync scheduler service
Handles automatic synchronization from Zoho CRM with per-category intervals
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

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'scheduler_settings.json')

# Sync categories with defaults
SYNC_CATEGORIES = {
    'candidates': {'default_interval': 30, 'description': 'Candidate records from Zoho CRM'},
    'interviews': {'default_interval': 30, 'description': 'Interview/meeting records'},
    'tasks': {'default_interval': 15, 'description': 'Task records linked to candidates'},
    'notes': {'default_interval': 60, 'description': 'CRM notes (incremental sync)'},
    'emails': {'default_interval': 120, 'description': 'Email history (last 30 days)'},
}


class SchedulerService:
    """Manages automatic sync scheduling with per-category intervals"""
    
    _scheduler: Optional[AsyncIOScheduler] = None
    _is_running: bool = False
    
    # Per-category state
    _intervals: Dict[str, int] = {}
    _sync_in_progress: Dict[str, bool] = {}
    _last_sync_time: Dict[str, Optional[datetime]] = {}
    _last_sync_result: Dict[str, Optional[Dict]] = {}
    _last_sync_error: Dict[str, Optional[str]] = {}
    
    @classmethod
    def _init_category_state(cls):
        """Initialize state for all categories"""
        for category in SYNC_CATEGORIES:
            if category not in cls._intervals:
                cls._intervals[category] = SYNC_CATEGORIES[category]['default_interval']
            if category not in cls._sync_in_progress:
                cls._sync_in_progress[category] = False
            if category not in cls._last_sync_time:
                cls._last_sync_time[category] = None
            if category not in cls._last_sync_result:
                cls._last_sync_result[category] = None
            if category not in cls._last_sync_error:
                cls._last_sync_error[category] = None
    
    @classmethod
    def _load_settings(cls):
        """Load settings from file"""
        cls._init_category_state()
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    # Handle legacy single interval
                    if 'sync_interval_minutes' in settings and 'candidates' not in settings:
                        old_interval = settings['sync_interval_minutes']
                        for category in SYNC_CATEGORIES:
                            cls._intervals[category] = old_interval
                    else:
                        # Load per-category intervals
                        for category in SYNC_CATEGORIES:
                            key = f"{category}_interval_minutes"
                            if key in settings:
                                cls._intervals[category] = settings[key]
                    logger.info(f"[Scheduler] Loaded settings: {cls._intervals}")
        except Exception as e:
            logger.warning(f"[Scheduler] Could not load settings: {e}")
    
    @classmethod
    def _save_settings(cls):
        """Save settings to file"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            settings = {}
            for category in SYNC_CATEGORIES:
                settings[f"{category}_interval_minutes"] = cls._intervals.get(category, SYNC_CATEGORIES[category]['default_interval'])
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            logger.warning(f"[Scheduler] Could not save settings: {e}")
    
    @classmethod
    def _load_last_sync_from_db(cls):
        """Load last sync info per category from database"""
        try:
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'alfa_platform.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                for category in SYNC_CATEGORIES:
                    cursor.execute("""
                        SELECT completed_at, records_processed, records_created, records_updated, errors 
                        FROM sync_logs 
                        WHERE sync_type = ? AND status = 'completed' 
                        ORDER BY completed_at DESC LIMIT 1
                    """, (category,))
                    row = cursor.fetchone()
                    if row:
                        cls._last_sync_time[category] = datetime.fromisoformat(row[0]) if row[0] else None
                        cls._last_sync_result[category] = {
                            'records_processed': row[1] or 0,
                            'records_created': row[2] or 0,
                            'records_updated': row[3] or 0,
                            'errors': row[4] or 0
                        }
                conn.close()
                logger.info(f"[Scheduler] Loaded last sync times from DB")
        except Exception as e:
            logger.warning(f"[Scheduler] Could not load last sync from DB: {e}")

    @classmethod
    async def start(cls, run_immediately: bool = False):
        """Start the scheduler with per-category intervals"""
        cls._load_settings()
        cls._load_last_sync_from_db()
        
        if cls._scheduler is not None:
            logger.warning("[Scheduler] Already running")
            return
        
        cls._scheduler = AsyncIOScheduler()
        cls._scheduler.add_listener(cls._job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        
        # Add a job for each category
        for category in SYNC_CATEGORIES:
            interval = cls._intervals.get(category, SYNC_CATEGORIES[category]['default_interval'])
            cls._scheduler.add_job(
                cls._create_sync_job(category),
                IntervalTrigger(minutes=interval),
                id=f'sync_{category}',
                name=f'Sync {category.title()}',
                replace_existing=True
            )
            logger.info(f"[Scheduler] Added job for {category} every {interval} minutes")
        
        cls._scheduler.start()
        cls._is_running = True
        logger.info(f"[Scheduler] Started with per-category intervals")
        
        if run_immediately:
            for category in SYNC_CATEGORIES:
                asyncio.create_task(cls._sync_category(category))

    @classmethod
    def _create_sync_job(cls, category: str):
        """Create a sync job function for a category"""
        async def job():
            await cls._sync_category(category)
        return job

    @classmethod
    async def _sync_category(cls, category: str):
        """Execute sync for a single category"""
        if cls._sync_in_progress.get(category, False):
            logger.warning(f"[Scheduler] {category} sync already in progress, skipping")
            return
        
        cls._sync_in_progress[category] = True
        cls._last_sync_time[category] = datetime.utcnow()
        
        try:
            from app.services.sync import SyncService
            
            result = None
            if category == 'candidates':
                result = await SyncService.sync_candidates_from_zoho()
            elif category == 'interviews':
                result = await SyncService.sync_interviews_from_zoho()
            elif category == 'tasks':
                result = await SyncService.sync_tasks_from_zoho()
            elif category == 'notes':
                result = await SyncService.sync_notes_from_zoho(full_sync=False)
            elif category == 'emails':
                result = await SyncService.sync_emails_from_zoho(days_back=30)
            
            cls._last_sync_result[category] = result
            cls._last_sync_error[category] = None
            logger.info(f"[Scheduler] {category} sync completed: {result.get('records_processed', 0)} processed")
            
        except Exception as e:
            cls._last_sync_error[category] = str(e)
            logger.error(f"[Scheduler] {category} sync failed: {e}")
        finally:
            cls._sync_in_progress[category] = False

    @classmethod
    async def stop(cls):
        """Stop the scheduler"""
        if cls._scheduler is not None:
            cls._scheduler.shutdown(wait=False)
            cls._scheduler = None
            cls._is_running = False
            logger.info("[Scheduler] Stopped")

    @classmethod
    async def trigger_sync(cls, category: str = None) -> Dict[str, Any]:
        """Trigger sync for one or all categories"""
        if category:
            if category not in SYNC_CATEGORIES:
                return {"error": f"Unknown category: {category}"}
            if cls._sync_in_progress.get(category, False):
                return {"error": f"{category} sync already in progress"}
            await cls._sync_category(category)
            return cls._last_sync_result.get(category) or {"message": f"{category} sync completed"}
        else:
            # Sync all categories sequentially
            results = {}
            for cat in SYNC_CATEGORIES:
                if not cls._sync_in_progress.get(cat, False):
                    await cls._sync_category(cat)
                    results[cat] = cls._last_sync_result.get(cat)
            return results

    @classmethod
    async def update_interval(cls, category: str, interval_minutes: int):
        """Update interval for a specific category"""
        if category not in SYNC_CATEGORIES:
            raise ValueError(f"Unknown category: {category}")
        
        cls._intervals[category] = interval_minutes
        cls._save_settings()
        
        if cls._scheduler:
            cls._scheduler.reschedule_job(
                f'sync_{category}',
                trigger=IntervalTrigger(minutes=interval_minutes)
            )
            logger.info(f"[Scheduler] {category} interval updated to {interval_minutes} minutes")

    @classmethod
    def _job_listener(cls, event):
        """Listen for job events"""
        if event.exception:
            logger.error(f"[Scheduler] Job failed: {event.exception}")

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Get current scheduler status with per-category info"""
        cls._init_category_state()
        
        categories_status = {}
        for category in SYNC_CATEGORIES:
            next_run = None
            if cls._scheduler:
                job = cls._scheduler.get_job(f'sync_{category}')
                if job and job.next_run_time:
                    next_run = job.next_run_time.isoformat()
            
            categories_status[category] = {
                'description': SYNC_CATEGORIES[category]['description'],
                'interval_minutes': cls._intervals.get(category, SYNC_CATEGORIES[category]['default_interval']),
                'sync_in_progress': cls._sync_in_progress.get(category, False),
                'last_sync_time': cls._last_sync_time[category].isoformat() if cls._last_sync_time.get(category) else None,
                'last_sync_result': cls._last_sync_result.get(category),
                'last_sync_error': cls._last_sync_error.get(category),
                'next_sync_time': next_run
            }
        
        return {
            'is_running': cls._is_running,
            'categories': categories_status
        }


async def start_scheduler(run_immediately: bool = False):
    await SchedulerService.start(run_immediately=run_immediately)


async def stop_scheduler():
    await SchedulerService.stop()
