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
from app.integrations.zoho.crm import ZohoCRM


class SyncService:
    """
    Service for synchronizing CRM data to local database.
    Enables fast dashboard queries without hitting Zoho API every time.
    """

    # Map Zoho Candidate Status to our pipeline stages
    STATUS_TO_STAGE_MAP = {
        # New Leads
        "New Candidate": "New Lead",
        "LinkedIn Applicants": "New Lead",
        "ZipRecruiter Leads": "New Lead",
        "LinkedIn Leads": "New Lead",
        "Requested Resume": "New Lead",

        # Screening
        "Screening": "Screening",
        "Automated Ai Review": "Screening",
        "Pre-Qualified": "Screening",
        "Qualified": "Screening",

        # Interview
        "To be invited for auto interview": "Interview Scheduled",
        "Auto Interview - Invited": "Interview Scheduled",
        "Invited to schedule interview": "Interview Scheduled",
        "Interview Scheduled": "Interview Scheduled",
        "Auto Interview - Done": "Interview Completed",
        "Auto Interview - In progress": "Interview Scheduled",
        "Invited to reschedule the interview": "Interview Scheduled",

        # Assessment
        "Language assessment assigned": "Assessment",
        "Lang. Assessment Assigned": "Assessment",
        "Language assessment to be graded": "Assessment",
        "Language assessment to be graded.": "Assessment",
        "Language assessment to be assigned": "Assessment",
        "Failed Lang. Assessment": "Assessment",

        # Offer
        "Offer Accepted": "Onboarding",
        "Offer Accepted Tier 2 (training)": "Onboarding",
        "Offer Accepted Tier 3 (training)": "Onboarding",
        "Offer Declined": "Inactive",

        # Onboarding
        "Documents Downloaded": "Onboarding",
        "ID Verification": "Onboarding",
        "Waiting Training": "Onboarding",
        "Waiting for Training": "Onboarding",
        "Invited for Upcoming Training": "Onboarding",
        "Booked for training": "Onboarding",
        "On training": "Onboarding",
        "Training Completed": "Onboarding",
        "Failed Training": "Onboarding",
        "Training No Show": "Onboarding",
        "Failed Onboarding": "Onboarding",
        "Waiting for System Specs Approval": "Onboarding",
        "Invited to AlfaOne": "Onboarding",

        # Active (Tier-based)
        "Tier 1": "Active",
        "Tier 2": "Active",
        "Tier 3": "Active",

        # Inactive/Lost
        "Lost Lead": "Inactive",
        "Lost Candidate": "Inactive",
        "Not Qualified": "Rejected",
        "Contact in Future": "Inactive",
        "Junk Lead": "Rejected",
    }

    @classmethod
    def map_status_to_stage(cls, candidate_status: str) -> str:
        """Map Zoho Candidate Status to our pipeline stage"""
        if not candidate_status:
            return "New Lead"

        # Direct mapping
        if candidate_status in cls.STATUS_TO_STAGE_MAP:
            return cls.STATUS_TO_STAGE_MAP[candidate_status]

        # Check for partial matches (for statuses with extra text)
        status_lower = candidate_status.lower()
        if "tier 1" in status_lower:
            return "Active"
        if "tier 2" in status_lower:
            return "Active"
        if "tier 3" in status_lower:
            return "Active"
        if "interview" in status_lower:
            return "Interview Scheduled"
        if "screening" in status_lower:
            return "Screening"
        if "assessment" in status_lower or "language" in status_lower:
            return "Assessment"
        if "training" in status_lower:
            return "Onboarding"
        if "onboarding" in status_lower or "document" in status_lower:
            return "Onboarding"
        if "lost" in status_lower or "declined" in status_lower:
            return "Inactive"
        if "qualified" in status_lower and "not" not in status_lower:
            return "Screening"

        # Default to New Lead if unknown
        return "New Lead"

    @classmethod
    async def sync_candidates_from_zoho(cls) -> Dict[str, Any]:
        """
        Sync candidates from Zoho CRM Leads module to local database.

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
                "errors": 0,
                "error_details": []
            }

            try:
                # Initialize Zoho CRM client
                crm = ZohoCRM()

                # Fetch leads from Zoho CRM
                # We'll fetch in batches using pagination
                page = 1
                per_page = 200

                while True:
                    try:
                        response = await crm.get_records(
                            module="Leads",
                            page=page,
                            per_page=per_page,
                            fields=[
                                "id", "First_Name", "Last_Name", "Email", "Phone", "Mobile",
                                "Candidate_Status", "Tier_Level", "Language", "Other_spoken_language_s",
                                "City", "State", "Country", "Service_Location",
                                "Candidate_Owner", "Candidate_Recruitment_Owner", "Client", "Agreed_Rate",
                                "Language_Assesment_Pased", "Language_Assessment_Grader",
                                "Language_Assessment_Completion_Date", "BGV_Passed", "Systems_Specs_Approved",
                                "Offer_Accepted", "Offer_accepted_date", "Training_Accepted",
                                "Training_Status", "Training_Start_Date", "Training_End_Date",
                                "Alfa_One_Fully_Onboarded", "Next_Followup", "Followup_Reason",
                                "Recontact_Date", "Last_Activity_Time", "Modified_Time",
                                "Candidate_Source", "Disqualification_Reason", "WhatsApp_Number"
                            ]
                        )

                        records = response.get("data", [])
                        if not records:
                            break

                        for record in records:
                            try:
                                created = await cls._upsert_candidate_from_zoho(db, record)
                                stats["records_processed"] += 1
                                if created:
                                    stats["records_created"] += 1
                                else:
                                    stats["records_updated"] += 1
                            except Exception as e:
                                print(f"Error processing candidate {record.get('id')}: {e}")
                                stats["errors"] += 1
                                stats["error_details"].append(str(e))

                        # Check if more pages exist
                        info = response.get("info", {})
                        if not info.get("more_records", False):
                            break

                        page += 1

                    except Exception as e:
                        print(f"Error fetching page {page}: {e}")
                        stats["errors"] += 1
                        stats["error_details"].append(f"Page {page}: {str(e)}")
                        break

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
    async def _upsert_candidate_from_zoho(cls, db: AsyncSession, data: Dict[str, Any]) -> bool:
        """
        Insert or update a candidate record from Zoho CRM data.

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

        # Parse helper functions
        def parse_date(value):
            if not value:
                return None
            try:
                if isinstance(value, datetime):
                    return value
                # Try ISO format first
                return datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
            except (ValueError, AttributeError):
                try:
                    # Try other common formats
                    return datetime.strptime(value, "%m/%d/%y %H:%M")
                except:
                    return None

        def parse_bool(value):
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "yes", "1")
            return bool(value)

        # Build full name
        first_name = data.get("First_Name", "")
        last_name = data.get("Last_Name", "")
        full_name = f"{first_name} {last_name}".strip() or "Unknown"

        # Get candidate status and map to stage
        candidate_status = data.get("Candidate_Status", "")
        stage = cls.map_status_to_stage(candidate_status)

        # Build languages string
        primary_lang = data.get("Language", "")
        other_langs = data.get("Other_spoken_language_s", "")
        languages = primary_lang
        if other_langs:
            languages = f"{primary_lang}; {other_langs}" if primary_lang else other_langs

        # Parse dates
        modified_time = parse_date(data.get("Modified_Time"))
        last_activity = parse_date(data.get("Last_Activity_Time"))
        next_followup = parse_date(data.get("Next_Followup"))
        recontact_date = parse_date(data.get("Recontact_Date"))
        offer_date = parse_date(data.get("Offer_accepted_date"))
        training_start = parse_date(data.get("Training_Start_Date"))
        training_end = parse_date(data.get("Training_End_Date"))
        la_date = parse_date(data.get("Language_Assessment_Completion_Date"))

        # Get owner names
        owner_data = data.get("Candidate_Owner", {})
        candidate_owner = owner_data.get("name") if isinstance(owner_data, dict) else str(owner_data) if owner_data else None

        recruitment_owner = data.get("Candidate_Recruitment_Owner", "")

        if existing:
            # Update existing record
            old_stage = existing.stage

            existing.first_name = first_name
            existing.last_name = last_name
            existing.full_name = full_name
            existing.email = data.get("Email")
            existing.phone = data.get("Phone")
            existing.mobile = data.get("Mobile")
            existing.whatsapp_number = data.get("WhatsApp_Number")

            existing.city = data.get("City")
            existing.state = data.get("State")
            existing.country = data.get("Country")
            existing.service_location = data.get("Service_Location")

            existing.candidate_status = candidate_status
            existing.stage = stage
            existing.tier = data.get("Tier_Level")

            existing.language = data.get("Language")
            existing.languages = languages

            existing.candidate_owner = candidate_owner
            existing.recruitment_owner = recruitment_owner
            existing.assigned_client = data.get("Client")
            existing.agreed_rate = data.get("Agreed_Rate")

            existing.language_assessment_passed = parse_bool(data.get("Language_Assesment_Pased"))
            existing.language_assessment_grader = data.get("Language_Assessment_Grader")
            existing.language_assessment_date = la_date
            existing.bgv_passed = parse_bool(data.get("BGV_Passed"))
            existing.system_specs_approved = parse_bool(data.get("Systems_Specs_Approved"))

            existing.offer_accepted = parse_bool(data.get("Offer_Accepted"))
            existing.offer_accepted_date = offer_date
            existing.training_accepted = parse_bool(data.get("Training_Accepted"))
            existing.training_status = data.get("Training_Status")
            existing.training_start_date = training_start
            existing.training_end_date = training_end
            existing.alfa_one_onboarded = parse_bool(data.get("Alfa_One_Fully_Onboarded"))

            existing.next_followup = next_followup
            existing.followup_reason = data.get("Followup_Reason")
            existing.recontact_date = recontact_date

            existing.last_activity_date = last_activity
            existing.zoho_modified_time = modified_time
            existing.candidate_source = data.get("Candidate_Source")
            existing.disqualification_reason = data.get("Disqualification_Reason")

            # Update stage tracking if stage changed
            if old_stage != stage:
                existing.stage_entered_date = datetime.utcnow()
                existing.days_in_stage = 0

            # Determine flags based on status
            status_lower = (candidate_status or "").lower()
            existing.needs_training = "training" in status_lower and "completed" not in status_lower
            existing.has_pending_documents = "document" in status_lower or "id verification" in status_lower

            existing.last_synced = datetime.utcnow()
            existing.updated_at = datetime.utcnow()

            return False

        else:
            # Create new record
            new_candidate = CandidateCache(
                zoho_id=str(zoho_id),
                zoho_module="Leads",
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                email=data.get("Email"),
                phone=data.get("Phone"),
                mobile=data.get("Mobile"),
                whatsapp_number=data.get("WhatsApp_Number"),

                city=data.get("City"),
                state=data.get("State"),
                country=data.get("Country"),
                service_location=data.get("Service_Location"),

                candidate_status=candidate_status,
                stage=stage,
                tier=data.get("Tier_Level"),

                language=data.get("Language"),
                languages=languages,

                candidate_owner=candidate_owner,
                recruitment_owner=recruitment_owner,
                assigned_client=data.get("Client"),
                agreed_rate=data.get("Agreed_Rate"),

                language_assessment_passed=parse_bool(data.get("Language_Assesment_Pased")),
                language_assessment_grader=data.get("Language_Assessment_Grader"),
                language_assessment_date=la_date,
                bgv_passed=parse_bool(data.get("BGV_Passed")),
                system_specs_approved=parse_bool(data.get("Systems_Specs_Approved")),

                offer_accepted=parse_bool(data.get("Offer_Accepted")),
                offer_accepted_date=offer_date,
                training_accepted=parse_bool(data.get("Training_Accepted")),
                training_status=data.get("Training_Status"),
                training_start_date=training_start,
                training_end_date=training_end,
                alfa_one_onboarded=parse_bool(data.get("Alfa_One_Fully_Onboarded")),

                next_followup=next_followup,
                followup_reason=data.get("Followup_Reason"),
                recontact_date=recontact_date,

                last_activity_date=last_activity,
                zoho_modified_time=modified_time,
                candidate_source=data.get("Candidate_Source"),
                disqualification_reason=data.get("Disqualification_Reason"),

                stage_entered_date=datetime.utcnow(),
                days_in_stage=0,
                needs_training="training" in (candidate_status or "").lower() and "completed" not in (candidate_status or "").lower(),
                has_pending_documents="document" in (candidate_status or "").lower(),
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
                    zoho_module="Leads",
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
