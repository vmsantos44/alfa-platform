"""
Alfa Operations Platform - Data Sync Service
Synchronizes data from Zoho CRM to local SQLite database
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.database_models import CandidateCache, Interview, Task, SyncLog
from app.integrations.zoho.crm import ZohoCRM


class SyncService:
    """
    Service for synchronizing CRM data to local database.
    Enables fast dashboard queries without hitting Zoho API every time.
    """

    # Map Zoho Candidate Status to our pipeline stages
    STATUS_TO_STAGE_MAP = {
        # New Candidates
        "New Candidate": "New Candidate",
        "LinkedIn Applicants": "New Candidate",
        "ZipRecruiter Leads": "New Candidate",
        "LinkedIn Leads": "New Candidate",
        "Requested Resume": "New Candidate",

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
        "Training Completed": "Active",  # Completed training = now active
        "Failed Training": "Inactive",
        "Training No Show": "Inactive",
        "Failed Onboarding": "Inactive",
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
            return "New Candidate"

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

        # Default to New Candidate if unknown
        return "New Candidate"

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
                                "Lead_Status", "Stage", "Tier_Level", "Language", "Other_spoken_language_s",
                                "City", "State", "Country", "Service_Location",
                                "Owner", "Candidate_Recruitment_Owner", "Client", "Agreed_Rate",
                                "Language_Assesment", "Language_Assessment_Graded_By",
                                "Language_Assessment_Completion_Date", "BGV_Passed", "Systems_Check_Approved",
                                "Offer_Accepted", "Offer_accepted_date", "Training_Accepted",
                                "Training_Status", "Training_Start_Date", "Training_End_Date",
                                "Alfa_One_Fully_Onboarded", "abrsmartfollowupextensionforzohocrm__Next_Followup",
                                "abrsmartfollowupextensionforzohocrm__Followup_Reason",
                                "Recontact_Date", "Last_Activity_Time", "Modified_Time", "Created_Time",
                                "Lead_Source", "Disqualification_Reason", "WhatsApp_Number"
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

        def to_string(value):
            """Convert value to string, handling lists and dicts"""
            if value is None:
                return None
            if isinstance(value, list):
                # Join list items with semicolon
                return "; ".join(str(v) for v in value if v)
            if isinstance(value, dict):
                # Get 'name' key if exists, else first string value
                return value.get("name") or value.get("id") or str(value)
            return str(value) if value else None

        # Build full name
        first_name = to_string(data.get("First_Name")) or ""
        last_name = to_string(data.get("Last_Name")) or ""
        full_name = f"{first_name} {last_name}".strip() or "Unknown"

        # Get lead status and map to stage
        lead_status = to_string(data.get("Lead_Status")) or ""
        stage = cls.map_status_to_stage(lead_status)

        # Build languages string
        primary_lang = to_string(data.get("Language")) or ""
        other_langs = to_string(data.get("Other_spoken_language_s")) or ""
        languages = primary_lang
        if other_langs:
            languages = f"{primary_lang}; {other_langs}" if primary_lang else other_langs

        # Parse dates
        modified_time = parse_date(data.get("Modified_Time"))
        created_time = parse_date(data.get("Created_Time"))  # When lead was created in Zoho
        last_activity = parse_date(data.get("Last_Activity_Time"))
        next_followup = parse_date(data.get("abrsmartfollowupextensionforzohocrm__Next_Followup"))
        recontact_date = parse_date(data.get("Recontact_Date"))
        offer_date = parse_date(data.get("Offer_accepted_date"))
        training_start = parse_date(data.get("Training_Start_Date"))
        training_end = parse_date(data.get("Training_End_Date"))
        la_date = parse_date(data.get("Language_Assessment_Completion_Date"))

        # Get owner names
        owner_data = data.get("Owner", {})
        candidate_owner = owner_data.get("name") if isinstance(owner_data, dict) else str(owner_data) if owner_data else None

        recruitment_owner_data = data.get("Candidate_Recruitment_Owner", {})
        recruitment_owner = recruitment_owner_data.get("name") if isinstance(recruitment_owner_data, dict) else to_string(recruitment_owner_data)

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

            existing.candidate_status = lead_status
            existing.stage = stage
            existing.tier = to_string(data.get("Tier_Level"))

            existing.language = to_string(data.get("Language"))
            existing.languages = languages

            existing.candidate_owner = candidate_owner
            existing.recruitment_owner = to_string(recruitment_owner)
            existing.assigned_client = to_string(data.get("Client"))
            existing.agreed_rate = to_string(data.get("Agreed_Rate"))

            existing.language_assessment_passed = parse_bool(data.get("Language_Assesment"))
            existing.language_assessment_grader = to_string(data.get("Language_Assessment_Graded_By"))
            existing.language_assessment_date = la_date
            existing.bgv_passed = parse_bool(data.get("BGV_Passed"))
            existing.system_specs_approved = parse_bool(data.get("Systems_Check_Approved"))

            existing.offer_accepted = parse_bool(data.get("Offer_Accepted"))
            existing.offer_accepted_date = offer_date
            existing.training_accepted = parse_bool(data.get("Training_Accepted"))
            existing.training_status = to_string(data.get("Training_Status"))
            existing.training_start_date = training_start
            existing.training_end_date = training_end
            existing.alfa_one_onboarded = parse_bool(data.get("Alfa_One_Fully_Onboarded"))

            existing.next_followup = next_followup
            existing.followup_reason = to_string(data.get("abrsmartfollowupextensionforzohocrm__Followup_Reason"))
            existing.recontact_date = recontact_date

            existing.last_activity_date = last_activity
            existing.zoho_modified_time = modified_time
            existing.zoho_created_time = created_time
            existing.candidate_source = to_string(data.get("Lead_Source"))
            existing.disqualification_reason = to_string(data.get("Disqualification_Reason"))

            # Update stage tracking if stage changed
            if old_stage != stage:
                # Use last_activity as stage entry date when stage changes
                existing.stage_entered_date = last_activity or datetime.utcnow()
                existing.days_in_stage = 0
            # If no stage_entered_date, use created_time (when lead was first added)
            elif not existing.stage_entered_date:
                existing.stage_entered_date = created_time or last_activity or datetime.utcnow()

            # Determine flags based on status
            status_lower = (lead_status or "").lower()
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

                city=to_string(data.get("City")),
                state=to_string(data.get("State")),
                country=to_string(data.get("Country")),
                service_location=to_string(data.get("Service_Location")),

                candidate_status=lead_status,
                stage=stage,
                tier=to_string(data.get("Tier_Level")),

                language=to_string(data.get("Language")),
                languages=languages,

                candidate_owner=candidate_owner,
                recruitment_owner=to_string(recruitment_owner),
                assigned_client=to_string(data.get("Client")),
                agreed_rate=to_string(data.get("Agreed_Rate")),

                language_assessment_passed=parse_bool(data.get("Language_Assesment")),
                language_assessment_grader=to_string(data.get("Language_Assessment_Graded_By")),
                language_assessment_date=la_date,
                bgv_passed=parse_bool(data.get("BGV_Passed")),
                system_specs_approved=parse_bool(data.get("Systems_Check_Approved")),

                offer_accepted=parse_bool(data.get("Offer_Accepted")),
                offer_accepted_date=offer_date,
                training_accepted=parse_bool(data.get("Training_Accepted")),
                training_status=to_string(data.get("Training_Status")),
                training_start_date=training_start,
                training_end_date=training_end,
                alfa_one_onboarded=parse_bool(data.get("Alfa_One_Fully_Onboarded")),

                next_followup=next_followup,
                followup_reason=to_string(data.get("abrsmartfollowupextensionforzohocrm__Followup_Reason")),
                recontact_date=recontact_date,

                last_activity_date=last_activity,
                zoho_modified_time=modified_time,
                zoho_created_time=created_time,
                candidate_source=to_string(data.get("Lead_Source")),
                disqualification_reason=to_string(data.get("Disqualification_Reason")),

                # Use created_time (when lead was added to Zoho) for stage entry
                stage_entered_date=created_time or last_activity or datetime.utcnow(),
                days_in_stage=0,  # Will be calculated by _update_days_in_stage
                needs_training="training" in (lead_status or "").lower() and "completed" not in (lead_status or "").lower(),
                has_pending_documents="document" in (lead_status or "").lower(),
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
                # New Candidates
                {"name": "Maria Santos", "email": "maria.santos@email.com", "stage": "New Candidate", "languages": "Spanish, Portuguese"},
                {"name": "Juan Garcia", "email": "juan.garcia@email.com", "stage": "New Candidate", "languages": "Spanish"},
                {"name": "Li Wei", "email": "li.wei@email.com", "stage": "New Candidate", "languages": "Mandarin, Cantonese"},

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

    @classmethod
    async def sync_interviews_from_zoho(cls) -> Dict[str, Any]:
        """
        Sync interviews from Zoho CRM Events module to local database.

        Fetches events that contain 'interview' in the title/subject and
        links them to candidates.

        Returns:
            Dict with sync statistics
        """
        async with async_session() as db:
            # Create sync log entry
            sync_log = SyncLog(
                sync_type="interviews",
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

                # Fetch events from Zoho CRM (interviews are stored as Events)
                page = 1
                per_page = 200

                while True:
                    try:
                        response = await crm.get_records(
                            module="Events",
                            page=page,
                            per_page=per_page,
                            fields=[
                                "id", "Event_Title", "Subject", "Start_DateTime", "End_DateTime",
                                "What_Id", "$se_module", "Owner", "Participants",
                                "Check_In_Status", "Description", "Created_Time", "Modified_Time"
                            ]
                        )

                        records = response.get("data", [])
                        if not records:
                            break

                        for record in records:
                            try:
                                # Only process events that look like interviews
                                title = record.get("Event_Title", "") or record.get("Subject", "") or ""
                                if not cls._is_interview_event(title):
                                    continue

                                created = await cls._upsert_interview_from_zoho(db, record)
                                stats["records_processed"] += 1
                                if created:
                                    stats["records_created"] += 1
                                else:
                                    stats["records_updated"] += 1
                            except Exception as e:
                                print(f"Error processing event {record.get('id')}: {e}")
                                stats["errors"] += 1
                                stats["error_details"].append(str(e))

                        # Check if more pages exist
                        info = response.get("info", {})
                        if not info.get("more_records", False):
                            break

                        page += 1

                    except Exception as e:
                        print(f"Error fetching events page {page}: {e}")
                        stats["errors"] += 1
                        stats["error_details"].append(f"Page {page}: {str(e)}")
                        break

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
    def _is_interview_event(cls, title: str) -> bool:
        """Check if an event title indicates it's an interview"""
        if not title:
            return False
        title_lower = title.lower()
        interview_keywords = [
            "interview", "screening", "auto interview", "candidate call",
            "hiring call", "recruitment call", "phone screen"
        ]
        return any(keyword in title_lower for keyword in interview_keywords)

    @classmethod
    async def _upsert_interview_from_zoho(cls, db: AsyncSession, data: Dict[str, Any]) -> bool:
        """
        Insert or update an interview record from Zoho CRM event data.

        Returns:
            True if created, False if updated
        """
        zoho_event_id = str(data.get("id"))
        if not zoho_event_id:
            return False

        # Check if exists
        result = await db.execute(
            select(Interview).where(Interview.zoho_event_id == zoho_event_id)
        )
        existing = result.scalar_one_or_none()

        # Parse date helpers - strip timezone to naive UTC for consistency
        def parse_datetime(value):
            if not value:
                return None
            try:
                if isinstance(value, datetime):
                    # Strip timezone if present
                    return value.replace(tzinfo=None) if value.tzinfo else value
                # Try ISO format
                dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
                # Strip timezone to make naive (consistent with rest of codebase)
                return dt.replace(tzinfo=None) if dt.tzinfo else dt
            except (ValueError, AttributeError):
                return None

        # Get event details
        title = data.get("Event_Title", "") or data.get("Subject", "") or "Interview"
        start_dt = parse_datetime(data.get("Start_DateTime"))
        end_dt = parse_datetime(data.get("End_DateTime"))

        if not start_dt:
            return False  # Skip events without a start time

        # Calculate duration
        duration_minutes = 30  # Default
        if start_dt and end_dt:
            duration = (end_dt - start_dt).total_seconds() / 60
            duration_minutes = int(duration) if duration > 0 else 30

        # Get related record (candidate) info
        what_id = data.get("What_Id")
        related_module = data.get("$se_module", "")

        # Try to get candidate ID
        zoho_candidate_id = None
        candidate_name = "Unknown"
        candidate_email = None

        if what_id:
            if isinstance(what_id, dict):
                zoho_candidate_id = what_id.get("id")
                candidate_name = what_id.get("name", "Unknown")
            else:
                zoho_candidate_id = str(what_id)

        # Get owner as interviewer
        owner_data = data.get("Owner", {})
        interviewer = owner_data.get("name") if isinstance(owner_data, dict) else str(owner_data) if owner_data else None

        # Determine interview status from Check_In_Status and date
        check_in_status = data.get("Check_In_Status", "")
        now = datetime.utcnow()

        if check_in_status:
            check_in_lower = str(check_in_status).lower()
            if "checked in" in check_in_lower or "completed" in check_in_lower:
                status = "completed"
                is_no_show = False
            elif "no show" in check_in_lower or "absent" in check_in_lower:
                status = "no_show"
                is_no_show = True
            elif "cancelled" in check_in_lower:
                status = "cancelled"
                is_no_show = False
            else:
                # Event is past but no check-in - likely no show
                if start_dt < now:
                    status = "no_show"
                    is_no_show = True
                else:
                    status = "scheduled"
                    is_no_show = False
        else:
            # No check-in status - determine by date
            if start_dt < now:
                # Past event with no status - assume completed unless very old
                days_ago = (now - start_dt).days
                if days_ago > 7:
                    status = "completed"  # Assume completed if more than a week old
                else:
                    status = "no_show"  # Recent past event with no check-in
                is_no_show = status == "no_show"
            else:
                status = "scheduled"
                is_no_show = False

        # Determine interview type from title
        title_lower = title.lower()
        if "auto interview" in title_lower:
            interview_type = "Auto Interview"
        elif "screening" in title_lower or "phone screen" in title_lower:
            interview_type = "Initial Screening"
        elif "final" in title_lower:
            interview_type = "Final Interview"
        else:
            interview_type = "Interview"

        if existing:
            # Update existing record
            existing.scheduled_date = start_dt
            existing.duration_minutes = duration_minutes
            existing.interview_type = interview_type
            existing.candidate_name = candidate_name
            existing.zoho_candidate_id = zoho_candidate_id
            existing.interviewer = interviewer
            existing.status = status
            # Only update is_no_show if changing to True (don't reset count)
            if is_no_show and not existing.is_no_show:
                existing.is_no_show = True
                existing.no_show_count = (existing.no_show_count or 0) + 1
            elif not is_no_show:
                existing.is_no_show = False
            existing.notes = data.get("Description")
            existing.updated_at = datetime.utcnow()

            return False
        else:
            # Create new record
            new_interview = Interview(
                zoho_event_id=zoho_event_id,
                candidate_name=candidate_name,
                candidate_email=candidate_email,
                zoho_candidate_id=zoho_candidate_id,
                scheduled_date=start_dt,
                duration_minutes=duration_minutes,
                interview_type=interview_type,
                status=status,
                is_no_show=is_no_show,
                no_show_count=1 if is_no_show else 0,
                interviewer=interviewer,
                notes=data.get("Description")
            )
            db.add(new_interview)
            return True

    @classmethod
    async def get_last_interview_sync(cls) -> Optional[datetime]:
        """Get the timestamp of the last successful interview sync"""
        async with async_session() as db:
            result = await db.execute(
                select(SyncLog)
                .where(SyncLog.sync_type == "interviews", SyncLog.status == "completed")
                .order_by(SyncLog.completed_at.desc())
                .limit(1)
            )
            sync_log = result.scalar_one_or_none()
            return sync_log.completed_at if sync_log else None

    # ========================================================================
    # TASK SYNC
    # ========================================================================

    @classmethod
    async def sync_tasks_from_zoho(cls) -> Dict[str, Any]:
        """
        Sync tasks from Zoho CRM Tasks module.
        Fetches open tasks and updates local database.
        """
        print("📋 Starting task sync from Zoho CRM...")

        async with async_session() as db:
            # Create sync log
            sync_log = SyncLog(
                sync_type="tasks",
                status="in_progress",
                started_at=datetime.utcnow()
            )
            db.add(sync_log)
            await db.commit()

            try:
                crm = ZohoCRM()
                stats = {
                    "total_fetched": 0,
                    "created": 0,
                    "updated": 0,
                    "errors": 0
                }

                page = 1
                has_more = True

                while has_more:
                    print(f"📋 Fetching tasks page {page}...")

                    response = await crm.get_records(
                        module="Tasks",
                        page=page,
                        per_page=100,
                        fields=[
                            "id", "Subject", "Due_Date", "Status", "Priority",
                            "What_Id", "$se_module", "Owner", "Created_By",
                            "Description", "Created_Time", "Modified_Time",
                            "Closed_Time"
                        ]
                    )

                    tasks = response.get("data", [])
                    info = response.get("info", {})

                    for task_data in tasks:
                        try:
                            is_new = await cls._upsert_task_from_zoho(db, task_data)
                            stats["total_fetched"] += 1
                            if is_new:
                                stats["created"] += 1
                            else:
                                stats["updated"] += 1
                        except Exception as e:
                            print(f"⚠️ Error syncing task {task_data.get('id')}: {e}")
                            stats["errors"] += 1

                    # Commit each page
                    await db.commit()

                    has_more = info.get("more_records", False)
                    page += 1

                    # Safety limit
                    if page > 50:
                        print("⚠️ Reached page limit (50)")
                        break

                # Update sync log
                sync_log.status = "completed"
                sync_log.completed_at = datetime.utcnow()
                sync_log.records_processed = stats["total_fetched"]
                sync_log.records_created = stats["created"]
                sync_log.records_updated = stats["updated"]
                await db.commit()

                print(f"✅ Task sync complete: {stats}")
                return stats

            except Exception as e:
                sync_log.status = "failed"
                sync_log.error_message = str(e)[:500]
                sync_log.completed_at = datetime.utcnow()
                await db.commit()
                raise

    @classmethod
    async def _upsert_task_from_zoho(cls, db: AsyncSession, data: Dict[str, Any]) -> bool:
        """
        Create or update a task from Zoho data.
        Returns True if created, False if updated.
        """
        zoho_task_id = str(data.get("id", ""))
        if not zoho_task_id:
            return False

        # Check if task exists
        result = await db.execute(
            select(Task).where(Task.zoho_task_id == zoho_task_id)
        )
        existing = result.scalar_one_or_none()

        # Parse dates
        due_date = cls._parse_date(data.get("Due_Date"))
        closed_time = cls._parse_datetime(data.get("Closed_Time"))

        # Get owner info
        owner_data = data.get("Owner", {})
        assigned_to = owner_data.get("name") if isinstance(owner_data, dict) else None

        # Get creator info
        creator_data = data.get("Created_By", {})
        created_by = creator_data.get("name") if isinstance(creator_data, dict) else None

        # Get related record (candidate)
        what_id_data = data.get("What_Id")
        zoho_candidate_id = None
        candidate_name = None
        if what_id_data and isinstance(what_id_data, dict):
            zoho_candidate_id = what_id_data.get("id")
            candidate_name = what_id_data.get("name")

        # Map Zoho status to our status
        zoho_status = data.get("Status", "Not Started")
        status_map = {
            "Not Started": "pending",
            "In Progress": "in_progress",
            "Completed": "completed",
            "Deferred": "pending",
            "Waiting for input": "pending"
        }
        status = status_map.get(zoho_status, "pending")

        # Map priority
        zoho_priority = data.get("Priority", "Medium")
        priority_map = {
            "High": "high",
            "Highest": "high",
            "Medium": "medium",
            "Normal": "medium",
            "Low": "low",
            "Lowest": "low"
        }
        priority = priority_map.get(zoho_priority, "medium")

        # Determine task type from subject
        subject = data.get("Subject", "Task")
        subject_lower = subject.lower()
        if "follow up" in subject_lower or "follow-up" in subject_lower:
            task_type = "follow_up"
        elif "document" in subject_lower or "ss" in subject_lower:
            task_type = "document_request"
        elif "training" in subject_lower:
            task_type = "training"
        elif "assessment" in subject_lower or "language" in subject_lower:
            task_type = "assessment"
        elif "interview" in subject_lower:
            task_type = "follow_up"
        else:
            task_type = "general"

        if existing:
            # Update existing task
            existing.title = subject
            existing.description = data.get("Description")
            existing.task_type = task_type
            existing.status = status
            existing.priority = priority
            existing.due_date = due_date
            existing.assigned_to = assigned_to
            existing.created_by = created_by
            existing.zoho_candidate_id = zoho_candidate_id
            existing.candidate_name = candidate_name
            existing.completed_at = closed_time
            existing.updated_at = datetime.utcnow()
            return False
        else:
            # Create new task
            new_task = Task(
                zoho_task_id=zoho_task_id,
                title=subject,
                description=data.get("Description"),
                task_type=task_type,
                status=status,
                priority=priority,
                due_date=due_date,
                assigned_to=assigned_to,
                created_by=created_by,
                zoho_candidate_id=zoho_candidate_id,
                candidate_name=candidate_name,
                completed_at=closed_time
            )
            db.add(new_task)
            return True

    @classmethod
    def _parse_date(cls, date_str: Optional[str]) -> Optional[datetime]:
        """Parse a date string (YYYY-MM-DD) to datetime"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    @classmethod
    def _parse_datetime(cls, value) -> Optional[datetime]:
        """Parse datetime value, handling various formats"""
        if not value:
            return None
        try:
            if isinstance(value, datetime):
                return value.replace(tzinfo=None) if value.tzinfo else value
            # Try ISO format
            dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, AttributeError, TypeError):
            return None

    @classmethod
    async def get_last_task_sync(cls) -> Optional[datetime]:
        """Get the timestamp of the last successful task sync"""
        async with async_session() as db:
            result = await db.execute(
                select(SyncLog)
                .where(SyncLog.sync_type == "tasks", SyncLog.status == "completed")
                .order_by(SyncLog.completed_at.desc())
                .limit(1)
            )
            sync_log = result.scalar_one_or_none()
            return sync_log.completed_at if sync_log else None

    # ========================================================================
    # NOTES SYNC
    # ========================================================================

    @classmethod
    def strip_html(cls, content: str) -> str:
        """
        Convert HTML to clean plain text using html2text library.

        Args:
            content: Text that may contain HTML tags

        Returns:
            Plain text with HTML converted to readable format
        """
        if not content:
            return ""

        import html2text
        import re

        # Configure html2text for clean output
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.ignore_emphasis = True
        h.ignore_tables = False
        h.body_width = 0  # Don't wrap lines
        h.unicode_snob = True  # Use unicode instead of ASCII

        try:
            # Convert HTML to text
            text = h.handle(content)
            # Clean up extra whitespace and newlines
            text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newlines
            text = re.sub(r'[ \t]+', ' ', text)  # Normalize spaces
            return text.strip()
        except Exception:
            # Fallback to simple regex stripping
            text = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()

    @classmethod
    def summarize_note(cls, content: str, max_length: int = 200) -> str:
        """
        Summarize note content using a simple heuristic approach.
        Extracts first sentence + last sentence if different, or truncates with ellipsis.

        Args:
            content: Raw note content
            max_length: Maximum length of summary

        Returns:
            Summarized text
        """
        if not content:
            return ""

        # Clean up whitespace
        content = content.strip()

        # If already short enough, return as-is
        if len(content) <= max_length:
            return content

        # Split into sentences (simple heuristic)
        import re
        sentences = re.split(r'(?<=[.!?])\s+', content)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            # No clear sentences, just truncate
            return content[:max_length - 3].rsplit(' ', 1)[0] + "..."

        first_sentence = sentences[0]

        # If just one sentence or first is long enough
        if len(sentences) == 1 or len(first_sentence) >= max_length - 20:
            if len(first_sentence) <= max_length:
                return first_sentence
            return first_sentence[:max_length - 3].rsplit(' ', 1)[0] + "..."

        # Try to include first and last sentence
        last_sentence = sentences[-1]

        # Avoid duplicating if first == last
        if first_sentence == last_sentence:
            if len(first_sentence) <= max_length:
                return first_sentence
            return first_sentence[:max_length - 3].rsplit(' ', 1)[0] + "..."

        combined = f"{first_sentence} [...] {last_sentence}"
        if len(combined) <= max_length:
            return combined

        # Just use first sentence with truncation if needed
        if len(first_sentence) <= max_length:
            return first_sentence
        return first_sentence[:max_length - 3].rsplit(' ', 1)[0] + "..."

    @classmethod
    def extract_key_phrases(cls, content: str, max_phrases: int = 5) -> list[str]:
        """
        Extract key phrases from note content using RAKE algorithm.

        Args:
            content: Raw note content
            max_phrases: Maximum number of phrases to extract

        Returns:
            List of key phrases
        """
        if not content or len(content) < 10:
            return []

        try:
            from rake_nltk import Rake

            # Initialize RAKE with default settings
            rake = Rake(
                min_length=1,
                max_length=3,
                include_repeated_phrases=False
            )

            # Extract keywords
            rake.extract_keywords_from_text(content)

            # Get ranked phrases (returns list of tuples: (score, phrase))
            ranked = rake.get_ranked_phrases_with_scores()

            # Filter and return top phrases
            phrases = []
            seen = set()
            for score, phrase in ranked[:max_phrases * 2]:  # Get more to filter
                # Clean up phrase
                phrase = phrase.strip().lower()

                # Skip very short or already seen
                if len(phrase) < 3 or phrase in seen:
                    continue

                # Skip common stopwords that might slip through
                if phrase in {'the', 'and', 'for', 'with', 'this', 'that', 'from'}:
                    continue

                seen.add(phrase)
                phrases.append(phrase)

                if len(phrases) >= max_phrases:
                    break

            return phrases

        except ImportError:
            # RAKE not installed, return empty
            print("⚠️ rake-nltk not installed, skipping key phrase extraction")
            return []
        except Exception as e:
            print(f"⚠️ Error extracting key phrases: {e}")
            return []

    @classmethod
    def summarize_with_phrases(cls, content: str, max_length: int = 200) -> dict:
        """
        Generate both a summary and key phrases for note content.

        Args:
            content: Raw note content
            max_length: Maximum length of summary

        Returns:
            Dict with 'summary' and 'key_phrases' keys
        """
        return {
            "summary": cls.summarize_note(content, max_length),
            "key_phrases": cls.extract_key_phrases(content)
        }

    @classmethod
    async def sync_notes_from_zoho(cls, full_sync: bool = False) -> Dict[str, Any]:
        """
        Sync notes from Zoho CRM Notes module to local database.
        Uses modified_since for incremental sync unless full_sync is True.

        Args:
            full_sync: If True, fetch all notes regardless of last sync time

        Returns:
            Dict with sync statistics
        """
        from app.models.database_models import CrmNote

        print("📝 Starting notes sync from Zoho CRM...")

        async with async_session() as db:
            # Create sync log
            sync_log = SyncLog(
                sync_type="notes",
                status="running",
                started_at=datetime.utcnow()
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
                crm = ZohoCRM()

                # Get last sync time for incremental sync
                modified_since = None
                if not full_sync:
                    last_sync = await cls.get_last_notes_sync()
                    if last_sync:
                        # Format as ISO string for Zoho API
                        modified_since = last_sync.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                        print(f"📝 Incremental sync since: {modified_since}")
                    else:
                        print("📝 No previous sync found, performing full sync")
                else:
                    print("📝 Full sync requested")

                page = 1
                per_page = 200

                while True:
                    try:
                        print(f"📝 Fetching notes page {page}...")

                        response = await crm.get_all_notes(
                            page=page,
                            per_page=per_page,
                            modified_since=modified_since
                        )

                        notes = response.get("data", [])
                        if not notes:
                            break

                        for note_data in notes:
                            try:
                                created = await cls._upsert_note_from_zoho(db, note_data)
                                stats["records_processed"] += 1
                                if created:
                                    stats["records_created"] += 1
                                else:
                                    stats["records_updated"] += 1
                            except Exception as e:
                                print(f"⚠️ Error processing note {note_data.get('id')}: {e}")
                                stats["errors"] += 1
                                stats["error_details"].append(str(e))

                        # Commit each page
                        await db.commit()

                        # Check for more pages
                        info = response.get("info", {})
                        if not info.get("more_records", False):
                            break

                        page += 1

                        # Safety limit
                        if page > 100:
                            print("⚠️ Reached page limit (100)")
                            break

                    except Exception as e:
                        print(f"❌ Error fetching notes page {page}: {e}")
                        stats["errors"] += 1
                        stats["error_details"].append(f"Page {page}: {str(e)}")
                        break

                # Mark sync as completed
                sync_log.status = "completed"
                sync_log.completed_at = datetime.utcnow()
                sync_log.records_processed = stats["records_processed"]
                sync_log.records_created = stats["records_created"]
                sync_log.records_updated = stats["records_updated"]
                sync_log.errors = stats["errors"]

                await db.commit()

                print(f"✅ Notes sync complete: {stats['records_processed']} processed, "
                      f"{stats['records_created']} created, {stats['records_updated']} updated")

            except Exception as e:
                sync_log.status = "failed"
                sync_log.error_message = str(e)[:500]
                sync_log.completed_at = datetime.utcnow()
                await db.commit()
                raise

            return stats

    @classmethod
    async def _upsert_note_from_zoho(cls, db: AsyncSession, data: Dict[str, Any]) -> bool:
        """
        Insert or update a CRM note from Zoho data.

        Returns:
            True if created, False if updated
        """
        from app.models.database_models import CrmNote

        zoho_note_id = str(data.get("id", ""))
        if not zoho_note_id:
            return False

        # Check if exists
        result = await db.execute(
            select(CrmNote).where(CrmNote.zoho_note_id == zoho_note_id)
        )
        existing = result.scalar_one_or_none()

        # Parse data and strip HTML from content
        title = data.get("Note_Title") or ""
        raw_content_original = data.get("Note_Content") or ""
        raw_content = cls.strip_html(raw_content_original)

        # Log if HTML was stripped (for debugging)
        if raw_content != raw_content_original:
            print(f"📝 Stripped HTML from note {zoho_note_id}: {len(raw_content_original)} -> {len(raw_content)} chars")

        # Get parent (candidate) info
        parent_id_data = data.get("Parent_Id")
        zoho_candidate_id = None
        if parent_id_data:
            if isinstance(parent_id_data, dict):
                zoho_candidate_id = parent_id_data.get("id")
            else:
                zoho_candidate_id = str(parent_id_data)

        parent_module = data.get("$se_module", "Leads")

        # Get owner info
        owner_data = data.get("Owner", {})
        created_by = owner_data.get("name") if isinstance(owner_data, dict) else str(owner_data) if owner_data else None

        # Parse dates
        created_time = cls._parse_datetime(data.get("Created_Time"))
        modified_time = cls._parse_datetime(data.get("Modified_Time"))

        # Generate summary and extract key phrases
        summary = cls.summarize_note(raw_content)
        phrases = cls.extract_key_phrases(raw_content)
        key_phrases_str = ', '.join(phrases) if phrases else None

        if existing:
            # Update existing note
            existing.title = title
            existing.raw_content = raw_content
            existing.summary = summary
            existing.key_phrases = key_phrases_str
            existing.zoho_candidate_id = zoho_candidate_id
            existing.parent_module = parent_module
            existing.created_by = created_by
            existing.zoho_created_time = created_time
            existing.zoho_modified_time = modified_time
            existing.updated_at = datetime.utcnow()
            return False
        else:
            # Create new note
            new_note = CrmNote(
                zoho_note_id=zoho_note_id,
                zoho_candidate_id=zoho_candidate_id,
                parent_module=parent_module,
                title=title,
                raw_content=raw_content,
                summary=summary,
                key_phrases=key_phrases_str,
                created_by=created_by,
                zoho_created_time=created_time,
                zoho_modified_time=modified_time
            )
            db.add(new_note)
            return True

    @classmethod
    async def get_last_notes_sync(cls) -> Optional[datetime]:
        """Get the timestamp of the last successful notes sync"""
        async with async_session() as db:
            result = await db.execute(
                select(SyncLog)
                .where(SyncLog.sync_type == "notes", SyncLog.status == "completed")
                .order_by(SyncLog.completed_at.desc())
                .limit(1)
            )
            sync_log = result.scalar_one_or_none()
            return sync_log.completed_at if sync_log else None

    # ========================================================================
    # EMAIL SYNC
    # ========================================================================

    @classmethod
    async def sync_emails_from_zoho(cls, days_back: int = 30, limit_candidates: Optional[int] = None) -> Dict[str, Any]:
        """
        Batch sync recent emails for all active candidates.
        Called on a schedule (every 30 minutes) to keep email cache fresh.

        Args:
            days_back: How many days of email history to fetch (default 30)
            limit_candidates: Optional limit on number of candidates to process (for testing)

        Returns:
            Dict with sync statistics
        """
        from app.models.database_models import CandidateEmail

        print(f"📧 Starting email sync from Zoho CRM (last {days_back} days)...")

        async with async_session() as db:
            # Create sync log
            sync_log = SyncLog(
                sync_type="emails",
                status="running",
                started_at=datetime.utcnow()
            )
            db.add(sync_log)
            await db.commit()

            stats = {
                "candidates_processed": 0,
                "emails_processed": 0,
                "emails_created": 0,
                "emails_updated": 0,
                "errors": 0,
                "error_details": []
            }

            try:
                crm = ZohoCRM()

                # Get active candidates (those in active pipeline stages)
                active_stages = [
                    "New Candidate", "Screening", "Interview Scheduled",
                    "Interview Completed", "Assessment", "Onboarding", "Active"
                ]

                query = select(CandidateCache).where(
                    CandidateCache.stage.in_(active_stages)
                ).order_by(CandidateCache.last_activity_date.desc())

                if limit_candidates:
                    query = query.limit(limit_candidates)

                result = await db.execute(query)
                candidates = result.scalars().all()

                print(f"📧 Processing emails for {len(candidates)} active candidates...")

                for candidate in candidates:
                    try:
                        candidate_stats = await cls._sync_emails_for_single_candidate(
                            db, crm, candidate.zoho_id, candidate.zoho_module, days_back
                        )
                        stats["candidates_processed"] += 1
                        stats["emails_processed"] += candidate_stats["processed"]
                        stats["emails_created"] += candidate_stats["created"]
                        stats["emails_updated"] += candidate_stats["updated"]

                        # Commit every 10 candidates to avoid holding locks
                        if stats["candidates_processed"] % 10 == 0:
                            await db.commit()
                            print(f"📧 Progress: {stats['candidates_processed']}/{len(candidates)} candidates")

                    except Exception as e:
                        print(f"⚠️ Error syncing emails for {candidate.zoho_id}: {e}")
                        stats["errors"] += 1
                        stats["error_details"].append(f"{candidate.zoho_id}: {str(e)[:100]}")

                # Final commit
                await db.commit()

                # Update sync log
                sync_log.status = "completed"
                sync_log.completed_at = datetime.utcnow()
                sync_log.records_processed = stats["emails_processed"]
                sync_log.records_created = stats["emails_created"]
                sync_log.records_updated = stats["emails_updated"]
                sync_log.errors = stats["errors"]

                await db.commit()

                print(f"✅ Email sync complete: {stats['candidates_processed']} candidates, "
                      f"{stats['emails_processed']} emails ({stats['emails_created']} new, "
                      f"{stats['emails_updated']} updated)")

            except Exception as e:
                sync_log.status = "failed"
                sync_log.error_message = str(e)[:500]
                sync_log.completed_at = datetime.utcnow()
                await db.commit()
                raise

            return stats

    @classmethod
    async def _sync_emails_for_single_candidate(
        cls,
        db: AsyncSession,
        crm: ZohoCRM,
        zoho_candidate_id: str,
        module: str,
        days_back: int = 30
    ) -> Dict[str, int]:
        """
        Sync emails for a single candidate.

        Args:
            db: Database session
            crm: Zoho CRM client
            zoho_candidate_id: Candidate's Zoho ID
            module: CRM module (Leads or Contacts)
            days_back: How many days of history to fetch

        Returns:
            Dict with processed/created/updated counts
        """
        stats = {"processed": 0, "created": 0, "updated": 0}

        page = 1
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        while True:
            try:
                response = await crm.get_emails_for_record(
                    module=module,
                    record_id=zoho_candidate_id,
                    page=page,
                    per_page=100
                )

                # Zoho returns emails in 'email_related_list' (not 'data' like other modules)
                emails = response.get("email_related_list", response.get("data", []))
                if not emails:
                    break

                for email_data in emails:
                    # Parse email date
                    email_time = cls._parse_email_datetime(email_data.get("Date_Time") or email_data.get("Time"))

                    # Skip emails older than cutoff (for batch sync)
                    if email_time and email_time < cutoff_date:
                        continue

                    created = await cls._upsert_email_from_zoho(
                        db, email_data, zoho_candidate_id, module
                    )
                    stats["processed"] += 1
                    if created:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

                # Check for more pages
                info = response.get("info", {})
                if not info.get("more_records", False):
                    break

                page += 1

                # Safety limit
                if page > 10:
                    break

            except Exception as e:
                print(f"⚠️ Error fetching emails page {page} for {zoho_candidate_id}: {e}")
                break

        return stats

    @classmethod
    async def sync_emails_for_candidate(
        cls,
        zoho_candidate_id: str,
        module: str = "Leads",
        include_history: bool = False
    ) -> Dict[str, Any]:
        """
        On-demand email sync for a specific candidate.
        Called when user views the Emails tab.

        Args:
            zoho_candidate_id: Candidate's Zoho ID
            module: CRM module (Leads or Contacts)
            include_history: If True, fetch all history (not just recent)

        Returns:
            Dict with sync stats and emails
        """
        from app.models.database_models import CandidateEmail

        print(f"📧 On-demand email sync for {zoho_candidate_id} (include_history={include_history})...")

        async with async_session() as db:
            crm = ZohoCRM()

            # Determine how far back to fetch
            if include_history:
                # Fetch all available emails
                days_back = 365 * 2  # 2 years
            else:
                # Just recent emails
                days_back = 30

            stats = await cls._sync_emails_for_single_candidate(
                db, crm, zoho_candidate_id, module, days_back
            )

            await db.commit()

            # Return the cached emails
            result = await db.execute(
                select(CandidateEmail)
                .where(CandidateEmail.zoho_candidate_id == zoho_candidate_id)
                .order_by(CandidateEmail.sent_at.desc())
            )
            emails = result.scalars().all()

            return {
                "stats": stats,
                "emails": emails,
                "total_count": len(emails)
            }

    @classmethod
    async def _upsert_email_from_zoho(
        cls,
        db: AsyncSession,
        data: Dict[str, Any],
        zoho_candidate_id: str,
        module: str
    ) -> bool:
        """
        Insert or update an email record from Zoho CRM data.

        Zoho email_related_list structure:
        {
            "message_id": "unique_hash",
            "subject": "Email Subject",
            "from": {"user_name": "Name", "email": "email@example.com"},
            "to": [{"user_name": "Name", "email": "email@example.com"}],
            "sent_time": "2025-11-29T01:48:52+03:00",
            "sent": true,  # true = outbound
            "has_attachment": false,
            "snippet": null,  # preview not available in list
            "owner": {"name": "Owner Name", "id": "123"}
        }

        Returns:
            True if created, False if updated
        """
        from app.models.database_models import CandidateEmail

        # Get unique email identifier - Zoho uses 'message_id' for emails
        zoho_email_id = str(data.get("message_id", "") or data.get("id", "") or data.get("Message_Id", ""))
        if not zoho_email_id:
            return False

        # Check if exists
        result = await db.execute(
            select(CandidateEmail).where(CandidateEmail.zoho_email_id == zoho_email_id)
        )
        existing = result.scalar_one_or_none()

        # Parse email data - Zoho uses lowercase keys
        from_data = data.get("from") or data.get("From") or {}
        to_data = data.get("to") or data.get("To") or []

        # Handle From field (dict with email key)
        if isinstance(from_data, dict):
            from_address = from_data.get("email", "") or from_data.get("Email", "")
        else:
            from_address = str(from_data) if from_data else ""

        # Handle To field (list of dicts)
        if isinstance(to_data, list):
            to_addresses = []
            for t in to_data:
                if isinstance(t, dict):
                    to_addresses.append(t.get("email", "") or t.get("Email", ""))
                else:
                    to_addresses.append(str(t))
            to_address = "; ".join(filter(None, to_addresses))
        elif isinstance(to_data, dict):
            to_address = to_data.get("email", "") or to_data.get("Email", "")
        else:
            to_address = str(to_data) if to_data else ""

        # Handle CC field
        cc_data = data.get("Cc") or data.get("cc") or []
        if isinstance(cc_data, list):
            cc_addresses = []
            for c in cc_data:
                if isinstance(c, dict):
                    cc_addresses.append(c.get("email", "") or c.get("Email", ""))
                else:
                    cc_addresses.append(str(c))
            cc_address = "; ".join(filter(None, cc_addresses)) or None
        else:
            cc_address = str(cc_data) if cc_data else None

        # Subject (Zoho uses lowercase)
        subject = data.get("subject") or data.get("Subject") or ""

        # Body - Zoho doesn't include body in list response, only snippet
        # The snippet may contain HTML, so convert to plain text
        raw_snippet = data.get("snippet") or ""
        body_snippet = cls.strip_html(raw_snippet)[:500] if raw_snippet else ""
        body_full = ""  # Would need separate API call for full body
        html_body = ""  # Will be set when fetching full email content

        # Parse sent date - Zoho uses 'sent_time' for emails
        sent_at = cls._parse_email_datetime(
            data.get("sent_time") or data.get("Sent_Time") or data.get("Date_Time") or data.get("Time")
        )
        if not sent_at:
            sent_at = datetime.utcnow()

        # Determine direction - Zoho uses 'sent' boolean (true = outbound from CRM)
        if data.get("sent") is True:
            direction = "outbound"
        elif data.get("sent") is False:
            direction = "inbound"
        else:
            # Fallback to activity type
            activity_type = str(data.get("Activity_Type") or data.get("type") or "")
            if activity_type.lower() in ("sent", "outbound"):
                direction = "outbound"
            elif activity_type.lower() in ("received", "inbound"):
                direction = "inbound"
            else:
                direction = "outbound"  # Default assumption

        # Check for attachments (Zoho uses lowercase)
        has_attachment = bool(data.get("has_attachment") or data.get("Has_Attachment") or data.get("Attachments"))

        # Message ID for threading
        message_id = data.get("Message_Id") or data.get("message_id")
        thread_id = data.get("Thread_Id") or data.get("thread_id")

        if existing:
            # Update existing
            existing.from_address = from_address
            existing.to_address = to_address
            existing.cc_address = cc_address
            existing.subject = subject
            existing.body_snippet = body_snippet
            # Don't overwrite body_full/html_body if already populated (from content fetch)
            if not existing.body_full:
                existing.body_full = body_full
            if not existing.html_body:
                existing.html_body = html_body
            existing.sent_at = sent_at
            existing.direction = direction
            existing.has_attachment = has_attachment
            existing.message_id = message_id
            existing.thread_id = thread_id
            existing.updated_at = datetime.utcnow()
            return False
        else:
            # Create new
            new_email = CandidateEmail(
                zoho_email_id=zoho_email_id,
                zoho_candidate_id=zoho_candidate_id,
                parent_module=module,
                direction=direction,
                from_address=from_address,
                to_address=to_address,
                cc_address=cc_address,
                subject=subject,
                body_snippet=body_snippet,
                body_full=body_full,
                html_body=html_body,
                sent_at=sent_at,
                has_attachment=has_attachment,
                message_id=message_id,
                thread_id=thread_id,
                source="crm"
            )
            db.add(new_email)
            return True

    @classmethod
    def _parse_email_datetime(cls, value) -> Optional[datetime]:
        """Parse email datetime from various Zoho formats"""
        if not value:
            return None
        try:
            if isinstance(value, datetime):
                return value.replace(tzinfo=None) if value.tzinfo else value

            # Try ISO format
            dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, AttributeError, TypeError):
            return None

    @classmethod
    async def get_email_thread_for_candidate(cls, zoho_candidate_id: str) -> Dict[str, Any]:
        """
        Get all emails for a candidate in chronological order.
        Designed for AI analysis to detect missed replies, stalled conversations, etc.

        Args:
            zoho_candidate_id: Candidate's Zoho ID

        Returns:
            Dict with emails in chronological order and analysis metadata
        """
        from app.models.database_models import CandidateEmail

        async with async_session() as db:
            # Get all emails for this candidate, oldest first (chronological)
            result = await db.execute(
                select(CandidateEmail)
                .where(CandidateEmail.zoho_candidate_id == zoho_candidate_id)
                .order_by(CandidateEmail.sent_at.asc())
            )
            emails = result.scalars().all()

            if not emails:
                return {
                    "candidate_id": zoho_candidate_id,
                    "emails": [],
                    "total_count": 0,
                    "last_inbound_at": None,
                    "last_outbound_at": None,
                    "days_since_last_response": None,
                    "needs_followup": False
                }

            # Find last inbound and outbound
            last_inbound = None
            last_outbound = None

            for email in reversed(emails):  # Start from most recent
                if email.direction == "inbound" and not last_inbound:
                    last_inbound = email.sent_at
                elif email.direction == "outbound" and not last_outbound:
                    last_outbound = email.sent_at

                if last_inbound and last_outbound:
                    break

            # Calculate days since last response
            days_since_last_response = None
            needs_followup = False

            if last_inbound:
                days_since = (datetime.utcnow() - last_inbound).days
                days_since_last_response = days_since

                # Check if we responded to their last email
                if last_outbound:
                    if last_inbound > last_outbound:
                        # They replied after our last email - we should respond
                        needs_followup = True if days_since >= 2 else False
                else:
                    # They emailed us but we never responded
                    needs_followup = True

            # Get candidate name
            candidate_result = await db.execute(
                select(CandidateCache)
                .where(CandidateCache.zoho_id == zoho_candidate_id)
            )
            candidate = candidate_result.scalar_one_or_none()
            candidate_name = candidate.full_name if candidate else None

            return {
                "candidate_id": zoho_candidate_id,
                "candidate_name": candidate_name,
                "emails": emails,
                "total_count": len(emails),
                "last_inbound_at": last_inbound,
                "last_outbound_at": last_outbound,
                "days_since_last_response": days_since_last_response,
                "needs_followup": needs_followup
            }

    @classmethod
    async def get_last_email_sync(cls) -> Optional[datetime]:
        """Get the timestamp of the last successful email sync"""
        async with async_session() as db:
            result = await db.execute(
                select(SyncLog)
                .where(SyncLog.sync_type == "emails", SyncLog.status == "completed")
                .order_by(SyncLog.completed_at.desc())
                .limit(1)
            )
            sync_log = result.scalar_one_or_none()
            return sync_log.completed_at if sync_log else None
