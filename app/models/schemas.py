"""
Alfa Operations Platform - Pydantic Schemas
Request/Response models for API endpoints
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ============================================
# Candidate Schemas
# ============================================

class CandidateBase(BaseModel):
    """Base candidate fields"""
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    stage: str = "New Candidate"
    assigned_client: Optional[str] = None
    tier: Optional[str] = None
    languages: Optional[str] = None


class CandidateResponse(CandidateBase):
    """Candidate response with computed fields"""
    id: int
    zoho_id: str
    zoho_module: str = "Contacts"
    last_activity_date: Optional[datetime] = None
    last_communication_date: Optional[datetime] = None
    days_in_stage: int = 0
    is_unresponsive: bool = False
    has_pending_documents: bool = False
    needs_training: bool = False
    zoho_url: Optional[str] = None

    class Config:
        from_attributes = True


class CandidateSummary(BaseModel):
    """Lightweight candidate for lists"""
    id: int
    zoho_id: str
    full_name: str
    stage: str
    days_in_stage: int = 0
    is_unresponsive: bool = False
    has_pending_documents: bool = False
    needs_training: bool = False
    tier: Optional[str] = None
    languages: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================
# Candidate Note Schemas
# ============================================

class CandidateNoteBase(BaseModel):
    """Base note fields"""
    content: str
    note_type: str = "general"


class CandidateNoteCreate(CandidateNoteBase):
    """Create a new note"""
    created_by: Optional[str] = None


class CandidateNoteResponse(CandidateNoteBase):
    """Note response"""
    id: int
    candidate_id: int
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CrmNoteResponse(BaseModel):
    """CRM Note response (synced from Zoho)"""
    id: int
    zoho_note_id: str
    zoho_candidate_id: Optional[str] = None
    parent_module: str = "Leads"
    title: Optional[str] = None
    summary: Optional[str] = None  # Summarized version for dashboard display
    raw_content: str  # Full note text
    key_phrases: Optional[list[str]] = None  # Key phrases extracted via RAKE
    created_by: Optional[str] = None
    zoho_created_time: Optional[datetime] = None
    zoho_modified_time: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_phrases(cls, note):
        """Convert ORM object, parsing key_phrases from comma-separated string"""
        phrases = None
        # Handle case where key_phrases column may not exist yet (pre-migration)
        key_phrases_str = getattr(note, 'key_phrases', None)
        if key_phrases_str:
            phrases = [p.strip() for p in key_phrases_str.split(',') if p.strip()]
        return cls(
            id=note.id,
            zoho_note_id=note.zoho_note_id,
            zoho_candidate_id=note.zoho_candidate_id,
            parent_module=note.parent_module,
            title=note.title,
            summary=note.summary,
            raw_content=note.raw_content,
            key_phrases=phrases,
            created_by=note.created_by,
            zoho_created_time=note.zoho_created_time,
            zoho_modified_time=note.zoho_modified_time
        )


# ============================================
# Candidate Detail Schema (Full profile)
# ============================================

class CandidateDetailResponse(BaseModel):
    """Full candidate detail with all fields"""
    id: int
    zoho_id: str
    zoho_module: str = "Leads"
    zoho_url: Optional[str] = None

    # Basic info
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    whatsapp_number: Optional[str] = None

    # Location
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    service_location: Optional[str] = None

    # Pipeline info
    candidate_status: Optional[str] = None
    stage: str
    tier: Optional[str] = None

    # Languages
    language: Optional[str] = None
    languages: Optional[str] = None

    # Assignment
    candidate_owner: Optional[str] = None
    recruitment_owner: Optional[str] = None
    assigned_client: Optional[str] = None
    agreed_rate: Optional[str] = None

    # Assessment tracking
    language_assessment_passed: Optional[bool] = None
    language_assessment_grader: Optional[str] = None
    language_assessment_date: Optional[datetime] = None
    bgv_passed: Optional[bool] = None
    system_specs_approved: Optional[bool] = None

    # Offer & Training
    offer_accepted: Optional[bool] = None
    offer_accepted_date: Optional[datetime] = None
    training_accepted: Optional[bool] = None
    training_status: Optional[str] = None
    training_start_date: Optional[datetime] = None
    training_end_date: Optional[datetime] = None
    alfa_one_onboarded: Optional[bool] = None

    # Follow-up tracking
    next_followup: Optional[datetime] = None
    followup_reason: Optional[str] = None
    recontact_date: Optional[datetime] = None

    # Activity tracking
    last_activity_date: Optional[datetime] = None
    last_communication_date: Optional[datetime] = None
    days_in_stage: int = 0
    stage_entered_date: Optional[datetime] = None

    # Status flags
    is_unresponsive: bool = False
    has_pending_documents: bool = False
    needs_training: bool = False
    disqualification_reason: Optional[str] = None

    # Source
    candidate_source: Optional[str] = None

    # Timestamps
    created_at: datetime
    updated_at: datetime
    zoho_created_time: Optional[datetime] = None

    # Related data
    notes: List["CandidateNoteResponse"] = []
    crm_notes: List["CrmNoteResponse"] = []  # Notes synced from Zoho CRM
    interviews: List["InterviewResponse"] = []
    tasks: List["TaskResponse"] = []

    class Config:
        from_attributes = True


# ============================================
# Action Alert Schemas
# ============================================

class ActionAlertBase(BaseModel):
    """Base alert fields"""
    alert_type: str
    priority: str = "medium"
    title: str
    description: Optional[str] = None


class ActionAlertCreate(ActionAlertBase):
    """Create a new alert"""
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    zoho_id: Optional[str] = None
    zoho_module: Optional[str] = None
    due_date: Optional[datetime] = None


class ActionAlertResponse(ActionAlertBase):
    """Alert response"""
    id: int
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    zoho_id: Optional[str] = None
    zoho_module: Optional[str] = None
    is_resolved: bool = False
    resolved_at: Optional[datetime] = None
    created_at: datetime
    due_date: Optional[datetime] = None

    class Config:
        from_attributes = True


class ResolveAlertRequest(BaseModel):
    """Request to resolve an alert"""
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None


# ============================================
# Interview Schemas
# ============================================

class InterviewBase(BaseModel):
    """Base interview fields"""
    candidate_name: str
    candidate_email: Optional[str] = None
    candidate_phone: Optional[str] = None
    scheduled_date: datetime
    duration_minutes: int = 30
    interview_type: str = "Initial Screening"
    interviewer: Optional[str] = None
    notes: Optional[str] = None


class InterviewCreate(InterviewBase):
    """Create a new interview"""
    candidate_id: Optional[int] = None
    zoho_candidate_id: Optional[str] = None


class InterviewResponse(InterviewBase):
    """Interview response"""
    id: int
    candidate_id: Optional[int] = None
    zoho_candidate_id: Optional[str] = None
    zoho_event_id: Optional[str] = None
    status: str = "scheduled"
    is_no_show: bool = False
    no_show_count: int = 0
    reschedule_count: int = 0
    outcome: Optional[str] = None
    teams_meeting_link: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InterviewUpdate(BaseModel):
    """Update interview"""
    scheduled_date: Optional[datetime] = None
    status: Optional[str] = None
    is_no_show: Optional[bool] = None
    outcome: Optional[str] = None
    notes: Optional[str] = None
    reschedule_reason: Optional[str] = None


class MarkNoShowRequest(BaseModel):
    """Mark interview as no-show"""
    send_followup: bool = True
    notes: Optional[str] = None


# ============================================
# Email Schemas
# ============================================

class CandidateEmailResponse(BaseModel):
    """Email response for candidate emails list"""
    id: int
    zoho_email_id: str
    zoho_candidate_id: str
    direction: str  # inbound, outbound, system
    from_address: str
    to_address: str
    cc_address: Optional[str] = None
    subject: Optional[str] = None
    body_snippet: Optional[str] = None
    body_full: Optional[str] = None
    sent_at: datetime
    has_attachment: bool = False
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    source: str = "crm"
    is_read: bool = True
    needs_response: bool = False

    class Config:
        from_attributes = True


class CandidateEmailsListResponse(BaseModel):
    """Response for list of candidate emails with metadata"""
    emails: List[CandidateEmailResponse] = []
    total_count: int = 0
    has_more: bool = False
    oldest_cached_date: Optional[datetime] = None
    newest_cached_date: Optional[datetime] = None
    cache_status: str = "cached"  # cached, fetching, partial


class EmailThreadResponse(BaseModel):
    """Email thread for AI analysis - chronological order"""
    candidate_id: str
    candidate_name: Optional[str] = None
    emails: List[CandidateEmailResponse] = []
    total_count: int = 0
    last_inbound_at: Optional[datetime] = None
    last_outbound_at: Optional[datetime] = None
    days_since_last_response: Optional[int] = None
    needs_followup: bool = False


# ============================================
# Task Schemas
# ============================================

class TaskBase(BaseModel):
    """Base task fields"""
    title: str
    description: Optional[str] = None
    task_type: str = "general"
    priority: str = "medium"
    due_date: Optional[datetime] = None


class TaskCreate(TaskBase):
    """Create a new task"""
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    zoho_candidate_id: Optional[str] = None
    assigned_to: Optional[str] = None


class TaskResponse(TaskBase):
    """Task response"""
    id: int
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    zoho_task_id: Optional[str] = None
    status: str = "pending"
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TaskUpdate(BaseModel):
    """Update task"""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    assigned_to: Optional[str] = None


# ============================================
# Dashboard Schemas
# ============================================

class PipelineStage(BaseModel):
    """Pipeline stage with count"""
    stage: str
    count: int
    candidates: List[CandidateSummary] = []


class DashboardStats(BaseModel):
    """Dashboard statistics"""
    needs_action_count: int = 0
    scheduled_today_count: int = 0
    active_interpreters_count: int = 0
    total_candidates: int = 0

    # Pipeline counts
    new_leads: int = 0
    screening: int = 0
    interview: int = 0
    assessment: int = 0
    onboarding: int = 0
    active: int = 0


class TodaySchedule(BaseModel):
    """Today's scheduled interviews"""
    interviews: List[InterviewResponse] = []
    total_count: int = 0


class DashboardResponse(BaseModel):
    """Full dashboard data"""
    stats: DashboardStats
    action_alerts: List[ActionAlertResponse] = []
    today_schedule: TodaySchedule
    pipeline: List[PipelineStage] = []
    overdue_tasks: List[TaskResponse] = []


# ============================================
# Sync Schemas
# ============================================

class SyncStatus(BaseModel):
    """Sync operation status"""
    sync_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    records_processed: int = 0
    records_created: int = 0
    records_updated: int = 0
    errors: int = 0
    error_message: Optional[str] = None


class SyncRequest(BaseModel):
    """Request to start sync"""
    sync_type: str = "full_sync"
    force: bool = False


# ============================================
# Generic Response Schemas
# ============================================

class SuccessResponse(BaseModel):
    """Generic success response"""
    success: bool = True
    message: str = "Operation completed successfully"


class ErrorResponse(BaseModel):
    """Error response"""
    success: bool = False
    error: str
    detail: Optional[str] = None


# Rebuild models to resolve forward references
CandidateDetailResponse.model_rebuild()
