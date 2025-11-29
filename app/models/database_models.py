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
    NEW_LEAD = "New Lead"
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
    zoho_module: Mapped[str] = mapped_column(String(20), default="Contacts")

    # Basic info
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Pipeline info
    stage: Mapped[str] = mapped_column(String(50), default="New Lead", index=True)
    assigned_client: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Languages (stored as comma-separated)
    languages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Activity tracking
    last_activity_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_communication_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    days_in_stage: Mapped[int] = mapped_column(Integer, default=0)
    stage_entered_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Status flags
    is_unresponsive: Mapped[bool] = mapped_column(Boolean, default=False)
    has_pending_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_training: Mapped[bool] = mapped_column(Boolean, default=False)

    # Sync metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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


class SyncLog(Base):
    """
    Track synchronization with Zoho CRM.
    Helps avoid redundant API calls.
    """
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_type: Mapped[str] = mapped_column(String(50), index=True)
    # types: candidates, interviews, tasks, full_sync

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
