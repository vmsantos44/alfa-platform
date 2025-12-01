"""
Alfa Operations Platform - SQLAlchemy Database Models
Local cache and tracking for operations data
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Text, Boolean, Float, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import enum


class AlertType(str, enum.Enum):
    """Types of action alerts"""
    NO_SHOW = "no_show"
    STUCK_PIPELINE = "stuck_pipeline"
    OVERDUE_TASK = "overdue_task"
    EXPIRED_DOCUMENT = "expired_document"
    PENDING_FOLLOWUP = "pending_followup"
    UNRESPONSIVE = "unresponsive"


class AlertPriority(str, enum.Enum):
    """Alert priority levels"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CandidateStage(str, enum.Enum):
    """Recruitment pipeline stages"""
    NEW_CANDIDATE = "New Candidate"
    SCREENING = "Screening"
    INTERVIEW_SCHEDULED = "Interview Scheduled"
    INTERVIEW_COMPLETED = "Interview Completed"
    ASSESSMENT = "Assessment"
    ONBOARDING = "Onboarding"
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    REJECTED = "Rejected"


class CandidateCache(Base):
    """
    Local cache of candidate data from Zoho CRM.
    Used for quick dashboard queries without hitting API every time.
    """
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    zoho_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    zoho_module: Mapped[str] = mapped_column(String(20), default="Leads")

    # Basic info
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    mobile: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    whatsapp_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Location
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    service_location: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # On-shore/Off-shore

    # Pipeline info from CRM
    candidate_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)  # Raw Zoho status
    stage: Mapped[str] = mapped_column(String(50), default="New Lead", index=True)  # Mapped pipeline stage
    tier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Tier 1, Tier 2, Tier 3

    # Languages
    language: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Primary language
    languages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # All languages

    # Assignment
    candidate_owner: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    recruitment_owner: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    assigned_client: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    agreed_rate: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Assessment tracking
    language_assessment_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    language_assessment_grader: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    language_assessment_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    bgv_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # Background check
    system_specs_approved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Offer & Training
    offer_accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    offer_accepted_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    training_accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    training_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    training_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    training_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    alfa_one_onboarded: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Follow-up tracking
    next_followup: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    followup_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    recontact_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Activity tracking
    last_activity_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_communication_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    days_in_stage: Mapped[int] = mapped_column(Integer, default=0)
    stage_entered_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Status flags
    is_unresponsive: Mapped[bool] = mapped_column(Boolean, default=False)
    has_pending_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_training: Mapped[bool] = mapped_column(Boolean, default=False)
    disqualification_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Source
    candidate_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Sync metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    zoho_modified_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    zoho_created_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # When lead was created in Zoho

    def __repr__(self):
        return f"<Candidate {self.full_name} ({self.stage})>"


class ActionAlert(Base):
    """
    Action alerts that need attention.
    These are generated from CRM data and user actions.
    """
    __tablename__ = "action_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Alert info
    alert_type: Mapped[str] = mapped_column(String(50), index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Related candidate (if applicable)
    candidate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    candidate_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    zoho_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zoho_module: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Status
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Alert {self.alert_type}: {self.title}>"


class Interview(Base):
    """
    Interview scheduling and tracking.
    Syncs with Zoho Calendar.
    """
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    zoho_event_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)

    # Candidate info
    candidate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    candidate_name: Mapped[str] = mapped_column(String(200))
    candidate_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    candidate_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zoho_candidate_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Schedule
    scheduled_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    interview_type: Mapped[str] = mapped_column(String(50), default="Initial Screening")

    # Status tracking
    status: Mapped[str] = mapped_column(String(30), default="scheduled", index=True)
    # statuses: scheduled, completed, no_show, cancelled, rescheduled

    # No-show tracking
    is_no_show: Mapped[bool] = mapped_column(Boolean, default=False)
    no_show_followup_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    no_show_count: Mapped[int] = mapped_column(Integer, default=0)

    # Rescheduling
    original_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0)
    reschedule_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Interviewer
    interviewer: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # outcomes: passed, failed, needs_review, pending

    # Teams integration
    teams_meeting_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Interview {self.candidate_name} @ {self.scheduled_date}>"


class Task(Base):
    """
    Tasks related to candidates or operations.
    Can sync with Zoho CRM tasks.
    """
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    zoho_task_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)

    # Task info
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(50), default="general")
    # types: follow_up, document_request, training, assessment, general

    # Related candidate
    candidate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    candidate_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    zoho_candidate_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Assignment
    assigned_to: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    # statuses: pending, in_progress, completed, cancelled
    priority: Mapped[str] = mapped_column(String(20), default="medium")

    # Dates
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Task {self.title} ({self.status})>"


class CandidateNote(Base):
    """
    Internal notes/comments on candidates.
    Allows team members to leave notes during recruitment.
    """
    __tablename__ = "candidate_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(Integer, index=True)

    # Note content
    content: Mapped[str] = mapped_column(Text)
    note_type: Mapped[str] = mapped_column(String(50), default="general")
    # types: general, interview, assessment, follow_up, document, system

    # Author
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CandidateNote {self.id} for candidate {self.candidate_id}>"


class SyncLog(Base):
    """
    Track synchronization with Zoho CRM.
    Helps avoid redundant API calls.
    """
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_type: Mapped[str] = mapped_column(String(50), index=True)
    # types: candidates, interviews, tasks, notes, full_sync

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Stats
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)

    # Status
    status: Mapped[str] = mapped_column(String(30), default="running")
    # statuses: running, completed, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self):
        return f"<SyncLog {self.sync_type} @ {self.started_at}>"


class CrmNote(Base):
    """
    Notes synced from Zoho CRM.
    Stores both raw content and summarized version for efficient dashboard display.
    """
    __tablename__ = "crm_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    zoho_note_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    # Related candidate (Zoho ID, since notes link to Leads/Contacts)
    zoho_candidate_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    parent_module: Mapped[str] = mapped_column(String(20), default="Leads")  # Leads or Contacts

    # Note content
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_content: Mapped[str] = mapped_column(Text)  # Full note text from CRM
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Summarized version
    key_phrases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Comma-separated key phrases from RAKE

    # Metadata from Zoho
    created_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    zoho_created_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    zoho_modified_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    # Local timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CrmNote {self.zoho_note_id} for {self.zoho_candidate_id}>"


class EmailDirection(str, enum.Enum):
    """Email direction types"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SYSTEM = "system"


class CandidateEmail(Base):
    """
    Email cache for candidate communications.
    Synced from Zoho CRM and used for:
    - Fast display in Emails tab
    - AI analysis for follow-up recommendations
    """
    __tablename__ = "candidate_emails"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Zoho identifiers
    zoho_email_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    zoho_candidate_id: Mapped[str] = mapped_column(String(50), index=True)
    parent_module: Mapped[str] = mapped_column(String(20), default="Leads")  # Leads or Contacts

    # Email direction and addresses
    direction: Mapped[str] = mapped_column(String(20), default="outbound")  # inbound, outbound, system
    from_address: Mapped[str] = mapped_column(String(300))
    to_address: Mapped[str] = mapped_column(String(500))  # May have multiple recipients
    cc_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Email content
    subject: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    body_snippet: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # First ~200 chars
    body_full: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Full body (HTML stripped)

    # Timestamps from Zoho
    sent_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # When email was sent/received

    # Email metadata
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    message_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # RFC message ID for threading
    thread_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # For grouping threads

    # Source tracking (for future: mailbox integration, etc.)
    source: Mapped[str] = mapped_column(String(50), default="crm")  # crm, mailbox, etc.

    # Status flags
    is_read: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_response: Mapped[bool] = mapped_column(Boolean, default=False)  # AI can set this

    # Local timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CandidateEmail {self.direction} {self.subject[:30] if self.subject else 'No subject'}>"
