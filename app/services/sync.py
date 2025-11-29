"""
Alfa Operations Platform - Data Sync Service
Synchronizes data from Zoho CRM to local SQLite database
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.database_models import CandidateCache, SyncLog
from app.integrations.zoho.crm import get_candidates_for_sidebar, get_crm_record_url


class SyncService:
    """
    Service for synchronizing CRM data to local database.
    Enables fast dashboard queries without hitting Zoho API every time.
    """

    # Candidate stages to sync
    STAGES_TO_SYNC = [
        "New Lead",
        "Screening",
        "Interview Scheduled",
        "Interview Completed",
        "Assessment",
        "Onboarding",
        "Active"
    ]

    @classmethod
    async def sync_candidates(cls, force: bool = False) -> Dict[str, Any]:
        """
        Sync candidates from Zoho CRM to local database.

        Args:
            force: If True, sync all candidates regardless of last sync time

        Returns:
            Dict with sync statistics
        """
        async with async_session() as db:
            # Create sync log entry
            sync_log = SyncLog(
                sync_type="candidates",
                status="running"
            )
            db.add(sync_log)
            await db.commit()

            stats = {
                "records_processed": 0,
                "records_created": 0,
                "records_updated": 0,
                "errors": 0
            }

            try:
                # Fetch candidates from CRM for each stage
                for stage in cls.STAGES_TO_SYNC:
                    try:
                        candidates = await get_candidates_for_sidebar(
                            stage=stage,
                            limit=100
                        )

                        for candidate_data in candidates:
                            try:
                                await cls._upsert_candidate(db, candidate_data)
                                stats["records_processed"] += 1
                            except Exception as e:
                                print(f"Error processing candidate: {e}")
                                stats["errors"] += 1

                    except Exception as e:
                        print(f"Error fetching stage {stage}: {e}")
                        stats["errors"] += 1

                # Update days_in_stage for all candidates
                await cls._update_days_in_stage(db)

                # Mark sync as completed
                sync_log.status = "completed"
                sync_log.completed_at = datetime.utcnow()
                sync_log.records_processed = stats["records_processed"]
                sync_log.records_created = stats["records_created"]
                sync_log.records_updated = stats["records_updated"]
                sync_log.errors = stats["errors"]

                await db.commit()

            except Exception as e:
                sync_log.status = "failed"
                sync_log.error_message = str(e)
                await db.commit()
                raise

            return stats

    @classmethod
    async def _upsert_candidate(cls, db: AsyncSession, data: Dict[str, Any]) -> bool:
        """
        Insert or update a candidate record.

        Returns:
            True if created, False if updated
        """
        zoho_id = data.get("id")
        if not zoho_id:
            return False

        # Check if exists
        result = await db.execute(
            select(CandidateCache).where(CandidateCache.zoho_id == str(zoho_id))
        )
        existing = result.scalar_one_or_none()

        # Parse dates
        last_comm = None
        if data.get("last_communication_date"):
            try:
                last_comm = datetime.fromisoformat(
                    data["last_communication_date"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        if existing:
            # Update existing record
            old_stage = existing.stage
            new_stage = data.get("stage", existing.stage)

            existing.full_name = data.get("name", existing.full_name)
            existing.email = data.get("email", existing.email)
            existing.phone = data.get("phone", existing.phone)
            existing.stage = new_stage
            existing.assigned_client = data.get("assigned_client")
            existing.tier = data.get("tier")
            existing.languages = data.get("languages")
            existing.last_communication_date = last_comm
            existing.zoho_module = data.get("module", "Contacts")

            # Update stage tracking if stage changed
            if old_stage != new_stage:
                existing.stage_entered_date = datetime.utcnow()
                existing.days_in_stage = 0

            # Update flags based on CRM data
            engagement = data.get("engagement", "medium")
            existing.is_unresponsive = engagement == "low" or data.get("is_unresponsive", False)

            status_indicators = data.get("status_indicators", [])
            existing.has_pending_documents = "credentials_pending" in status_indicators
            existing.needs_training = "training_required" in status_indicators

            existing.last_synced = datetime.utcnow()
            existing.updated_at = datetime.utcnow()

            return False

        else:
            # Create new record
            new_candidate = CandidateCache(
                zoho_id=str(zoho_id),
                zoho_module=data.get("module", "Contacts"),
                full_name=data.get("name", "Unknown"),
                email=data.get("email"),
                phone=data.get("phone"),
                stage=data.get("stage", "New Lead"),
                assigned_client=data.get("assigned_client"),
                tier=data.get("tier"),
                languages=data.get("languages"),
                last_communication_date=last_comm,
                stage_entered_date=datetime.utcnow(),
                days_in_stage=0,
                is_unresponsive=data.get("engagement") == "low",
                has_pending_documents="credentials_pending" in data.get("status_indicators", []),
                needs_training="training_required" in data.get("status_indicators", []),
                last_synced=datetime.utcnow()
            )
            db.add(new_candidate)
            return True

    @classmethod
    async def _update_days_in_stage(cls, db: AsyncSession):
        """Update days_in_stage for all candidates"""
        result = await db.execute(select(CandidateCache))
        candidates = result.scalars().all()

        now = datetime.utcnow()
        for candidate in candidates:
            if candidate.stage_entered_date:
                delta = now - candidate.stage_entered_date
                candidate.days_in_stage = delta.days

        await db.commit()

    @classmethod
    async def get_last_sync(cls) -> Optional[datetime]:
        """Get the timestamp of the last successful sync"""
        async with async_session() as db:
            result = await db.execute(
                select(SyncLog)
                .where(SyncLog.sync_type == "candidates", SyncLog.status == "completed")
                .order_by(SyncLog.completed_at.desc())
                .limit(1)
            )
            sync_log = result.scalar_one_or_none()
            return sync_log.completed_at if sync_log else None

    @classmethod
    async def create_sample_data(cls):
        """
        Create sample data for testing the dashboard.
        Call this if you don't have Zoho CRM connected yet.
        """
        async with async_session() as db:
            # Check if we already have data
            result = await db.execute(select(CandidateCache).limit(1))
            if result.scalar_one_or_none():
                return {"message": "Data already exists"}

            sample_candidates = [
                # New Leads
                {"name": "Maria Santos", "email": "maria.santos@email.com", "stage": "New Lead", "languages": "Spanish, Portuguese"},
                {"name": "Juan Garcia", "email": "juan.garcia@email.com", "stage": "New Lead", "languages": "Spanish"},
                {"name": "Li Wei", "email": "li.wei@email.com", "stage": "New Lead", "languages": "Mandarin, Cantonese"},

                # Screening
                {"name": "Ahmed Hassan", "email": "ahmed.h@email.com", "stage": "Screening", "languages": "Arabic", "days": 8, "unresponsive": True},
                {"name": "Fatima Al-Hassan", "email": "fatima.ah@email.com", "stage": "Screening", "languages": "Arabic, French"},

                # Interview Scheduled
                {"name": "Ana Rodriguez", "email": "ana.r@email.com", "stage": "Interview Scheduled", "languages": "Spanish"},
                {"name": "Carlos Mendez", "email": "carlos.m@email.com", "stage": "Interview Scheduled", "languages": "Spanish, English"},
                {"name": "Yuki Tanaka", "email": "yuki.t@email.com", "stage": "Interview Scheduled", "languages": "Japanese"},

                # Assessment
                {"name": "Pierre Dubois", "email": "pierre.d@email.com", "stage": "Assessment", "languages": "French", "days": 5},
                {"name": "Kim Soo-yeon", "email": "kim.sy@email.com", "stage": "Assessment", "languages": "Korean"},

                # Onboarding
                {"name": "Olga Petrova", "email": "olga.p@email.com", "stage": "Onboarding", "languages": "Russian, Ukrainian"},

                # Active
                {"name": "Sofia Martinez", "email": "sofia.m@email.com", "stage": "Active", "languages": "Spanish"},
                {"name": "Hiroshi Yamamoto", "email": "hiroshi.y@email.com", "stage": "Active", "languages": "Japanese"},
                {"name": "Elena Popescu", "email": "elena.p@email.com", "stage": "Active", "languages": "Romanian, Italian"},
            ]

            now = datetime.utcnow()
            for i, data in enumerate(sample_candidates):
                days_back = data.get("days", i % 7)
                candidate = CandidateCache(
                    zoho_id=f"SAMPLE_{i+1:04d}",
                    zoho_module="Contacts",
                    full_name=data["name"],
                    email=data["email"],
                    stage=data["stage"],
                    languages=data["languages"],
                    stage_entered_date=now - timedelta(days=days_back),
                    days_in_stage=days_back,
                    is_unresponsive=data.get("unresponsive", False),
                    last_synced=now
                )
                db.add(candidate)

            await db.commit()
            return {"message": f"Created {len(sample_candidates)} sample candidates"}
