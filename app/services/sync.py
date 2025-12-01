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
        closed_time = parse_datetime(data.get("Closed_Time"))

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
