# Alfa Operations Platform - Handoff Document

## Project Overview

**Alfa Operations Platform** is a unified operations dashboard for interpreter recruitment. It syncs candidate and interview data from Zoho CRM and provides a streamlined interface for managing the recruitment pipeline, scheduling, and reporting.

- **Live URL**: https://platform.alfacrm.site
- **Server**: 45.55.32.243:8003
- **Repository**: https://github.com/vmsantos44/alfa-platform
- **Branch**: `vibrant-solomon`

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI (Python 3.12) |
| Database | SQLite with SQLAlchemy async (aiosqlite) |
| Frontend | Jinja2 Templates + Alpine.js + Tailwind CSS |
| CRM Integration | Zoho CRM API (OAuth 2.0) |
| Mail Integration | Zoho Mail API (separate OAuth client) |
| Bookings Integration | Zoho Bookings API (separate OAuth client) |
| Task Scheduler | APScheduler |
| Charts | Chart.js |
| Server | Ubuntu with systemd |

---

## Features Implemented

### 1. Zoho CRM Sync
- Syncs candidates from Zoho CRM Leads module
- Syncs interviews from Zoho CRM Events module
- Maps Zoho `Lead_Status` to 9 pipeline stages
- Auto-sync every 30 minutes (configurable)
- Manual sync trigger available
- SQLite WAL mode for concurrent access

### 2. Candidate Pipeline
- **Pipeline View**: Kanban-style board with drag indicators
- **List View**: Table view with sorting
- **9 Stages**: New Candidate → Screening → Interview Scheduled → Interview Completed → Assessment → Onboarding → Active → Inactive → Rejected

### 3. Advanced Filters
- Multi-select: Stage, Language, Owner, Tier Level
- Range filters: Days in Stage (min/max), Last Activity date
- Status checkboxes: Unresponsive, Pending Docs, Needs Training, Lang Assessment Passed, BGV Passed, System Specs Approved, Offer Accepted
- URL params for shareable filter links
- Saved filter presets (localStorage)

### 4. Candidate Detail Page (`/candidates/{id}`)
- **Profile Tab**: All candidate info (contact, location, languages, assignment, assessment, training)
- **Activity Tab**: Interview history, tasks list
- **Notes Tab**: Add/delete internal notes with types
- **Documents Tab**: Placeholder (links to Zoho)

### 5. Dashboard Analytics
- Pipeline funnel chart
- Top languages chart
- Tier distribution chart
- Candidates by owner chart
- Recent activity feed

### 6. Scheduling Module (`/scheduling`)
- **Calendar View**: Monthly calendar with interview events
- **Today's Interviews**: Sidebar showing today's scheduled interviews with quick actions
- **No-Shows Section**:
  - Filterable by date range (7, 30, 90 days, all time)
  - Pagination with "Load More"
  - Pending follow-up checkbox
  - Reschedule and Follow-up Sent actions
- **Stats Cards**: Today count, This Week, No-Shows (30d), Completion Rate
- **Interview Management**: Create, complete, mark no-show, reschedule

### 7. Reports Module (`/reports`)
- Weekly Summary with stats
- Interview metrics
- No-show tracking

### 8. Auto-Sync Scheduler
- Configurable interval (5 min to 24 hours)
- Syncs both candidates AND interviews
- Start/Stop from Settings page
- Shows next sync time, last sync results
- Prevents overlapping syncs

### 9. Zoho Mail Integration
- **OAuth Flow**: `/oauth/authorize` and `/oauth/callback` endpoints
- **Send Emails**: Send emails via Zoho Mail API
- **Get Emails**: Fetch inbox, folders, search emails
- **Contact History**: Get all emails sent to/from a specific email address
- **Use Case**: Display email history on candidate profiles

---

## Project Structure

```
alfa-platform/
├── app/
│   ├── main.py                 # FastAPI app, routes, lifespan
│   ├── config.py               # Environment configuration
│   ├── core/
│   │   └── database.py         # SQLAlchemy async setup, WAL mode
│   ├── models/
│   │   ├── database_models.py  # SQLAlchemy models
│   │   └── schemas.py          # Pydantic schemas
│   ├── routes/
│   │   ├── candidates.py       # Candidate CRUD, pipeline, notes
│   │   ├── dashboard.py        # Dashboard stats, analytics
│   │   ├── sync.py             # Sync + scheduler endpoints
│   │   ├── interviews.py       # Interview CRUD, no-show tracking
│   │   ├── reports.py          # Reports and analytics
│   │   └── ...
│   ├── services/
│   │   ├── sync.py             # Zoho sync logic (candidates + interviews)
│   │   └── scheduler.py        # APScheduler service
│   └── integrations/
│       └── zoho/
│           ├── auth.py         # OAuth 2.0 token management
│           ├── crm.py          # Zoho CRM API client
│           ├── mail.py         # Zoho Mail API client (separate OAuth)
│           └── bookings.py     # Zoho Bookings API client (separate OAuth)
├── templates/
│   ├── base.html               # Base layout with sidebar
│   ├── dashboard.html          # Dashboard with charts
│   ├── candidates.html         # Pipeline/list views
│   ├── candidate_detail.html   # Full candidate profile
│   ├── scheduling.html         # Interview calendar and no-show tracking
│   ├── reports.html            # Reports and analytics
│   ├── settings.html           # Settings + auto-sync controls
│   └── ...
├── static/                     # Static assets
├── data/                       # SQLite database location
├── requirements.txt            # Python dependencies
└── HANDOFF.md                  # This document
```

---

## Database Models

### CandidateCache
Main candidate table synced from Zoho CRM.

| Field | Type | Description |
|-------|------|-------------|
| id | int | Primary key |
| zoho_id | str | Zoho CRM Lead ID |
| full_name | str | Candidate name |
| email | str | Email address |
| phone | str | Phone number |
| stage | str | Pipeline stage |
| tier | str | Tier 1/2/3 |
| languages | str | Languages (semicolon-separated) |
| candidate_owner | str | Assigned recruiter |
| days_in_stage | int | Days in current stage |
| is_unresponsive | bool | Unresponsive flag |
| has_pending_documents | bool | Pending docs flag |
| needs_training | bool | Needs training flag |
| language_assessment_passed | bool | Assessment status |
| bgv_passed | bool | Background check status |
| system_specs_approved | bool | System specs status |
| offer_accepted | bool | Offer status |
| ... | ... | Many more fields |

### Interview
Interview scheduling and tracking (synced from Zoho Events).

| Field | Type | Description |
|-------|------|-------------|
| id | int | Primary key |
| zoho_event_id | str | Zoho CRM Event ID |
| candidate_id | int | FK to candidate (nullable) |
| candidate_name | str | Candidate name |
| candidate_email | str | Email |
| scheduled_date | datetime | Interview date/time |
| duration_minutes | int | Duration (default 30) |
| interview_type | str | Auto Interview, Initial Screening, etc. |
| status | str | scheduled, completed, no_show, cancelled |
| is_no_show | bool | No-show flag |
| no_show_count | int | Number of no-shows by this candidate |
| no_show_followup_sent | bool | Follow-up sent flag |
| reschedule_count | int | Times rescheduled |
| interviewer | str | Interviewer name |
| outcome | str | passed, failed, needs_review |

### CandidateNote
Internal notes on candidates.

| Field | Type | Description |
|-------|------|-------------|
| id | int | Primary key |
| candidate_id | int | FK to candidate |
| content | text | Note content |
| note_type | str | general/interview/assessment/follow_up/document |
| created_by | str | Author name |
| created_at | datetime | Timestamp |

### SyncLog, ActionAlert, Task
Supporting tables for sync tracking, alerts, and tasks.

---

## Key API Endpoints

### Candidates
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/candidates/` | List candidates with filters |
| GET | `/api/candidates/{id}` | Get candidate summary |
| GET | `/api/candidates/{id}/detail` | Get full candidate detail |
| GET | `/api/candidates/pipeline` | Get pipeline with counts |
| POST | `/api/candidates/{id}/move-stage` | Move to new stage |
| POST | `/api/candidates/{id}/flag-unresponsive` | Toggle unresponsive |
| GET | `/api/candidates/{id}/notes` | Get candidate notes |
| POST | `/api/candidates/{id}/notes` | Add note |
| DELETE | `/api/candidates/{id}/notes/{note_id}` | Delete note |

### Interviews
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/interviews/` | List interviews with filters |
| GET | `/api/interviews/today` | Today's interviews |
| GET | `/api/interviews/no-shows` | No-shows (with date/pagination filters) |
| GET | `/api/interviews/no-shows/count` | Count for pagination |
| GET | `/api/interviews/calendar/{year}/{month}` | Calendar data |
| GET | `/api/interviews/stats/summary` | Stats (today, week, no-shows, completion rate) |
| POST | `/api/interviews/` | Create interview |
| POST | `/api/interviews/{id}/no-show` | Mark as no-show |
| POST | `/api/interviews/{id}/complete` | Mark as completed |
| POST | `/api/interviews/{id}/reschedule` | Reschedule |
| POST | `/api/interviews/{id}/followup-sent` | Mark follow-up sent |

### Sync & Scheduler
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sync/scheduler/status` | Get scheduler status |
| POST | `/api/sync/scheduler/start` | Start auto-sync |
| POST | `/api/sync/scheduler/stop` | Stop auto-sync |
| POST | `/api/sync/scheduler/trigger` | Trigger sync now |
| PUT | `/api/sync/scheduler/interval` | Update sync interval |
| POST | `/api/sync/candidates` | Manual candidate sync |
| POST | `/api/sync/interviews` | Manual interview sync |
| GET | `/api/sync/debug-zoho` | Debug Zoho CRM data |
| GET | `/api/sync/debug-events` | Debug Zoho Events |
| GET | `/api/sync/debug-bookings` | Debug Zoho Bookings |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard/stats` | Dashboard statistics |
| GET | `/api/dashboard/analytics/pipeline-funnel` | Funnel data |
| GET | `/api/dashboard/analytics/by-language` | Language breakdown |
| GET | `/api/dashboard/analytics/by-tier` | Tier breakdown |
| GET | `/api/dashboard/analytics/by-owner` | Owner breakdown |
| GET | `/api/dashboard/analytics/recent-activity` | Recent activity |

### Zoho Mail
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/oauth/authorize` | Start OAuth flow for Zoho Mail |
| GET | `/oauth/callback` | OAuth callback (automatic) |
| GET | `/api/mail/test` | Test mail connection |
| GET | `/api/mail/folders` | List all mail folders |
| GET | `/api/mail/emails` | Get emails from inbox |
| GET | `/api/mail/emails/{id}` | Get specific email with content |
| GET | `/api/mail/search?q=...` | Search emails |
| GET | `/api/mail/contact/{email}` | Get email history for a contact |
| POST | `/api/mail/send` | Send an email |

---

## Zoho Integration

### Zoho CRM (Primary)
- OAuth 2.0 with refresh token
- Syncs Leads (candidates) and Events (interviews)
- Auto-refresh on token expiry

### Zoho Mail (Separate Client)
- **Purpose**: Send/receive emails, show email history on candidate profiles
- **Status**: Fully implemented and working
- **OAuth Flow**: `/oauth/authorize` → Zoho login → `/oauth/callback`
- **Connected Account**: vsantos@alfasystemscv.com
- **Location**: `app/integrations/zoho/mail.py`
- **Scopes**: `ZohoMail.messages.ALL`, `ZohoMail.accounts.READ`, `ZohoMail.folders.READ`

### Zoho Bookings (Separate Client)
- **Purpose**: Get accurate appointment status (COMPLETED, NO_SHOW, CANCEL)
- **Status**: Partially implemented - API returning errors
- **Note**: Has its own OAuth credentials separate from CRM
- **Location**: `app/integrations/zoho/bookings.py`

### Environment Variables
```env
# Zoho CRM (primary)
ZOHO_CLIENT_ID=your_client_id
ZOHO_CLIENT_SECRET=your_client_secret
ZOHO_REFRESH_TOKEN=your_refresh_token
ZOHO_ORG_ID=815230494

# Zoho Bookings (separate client - optional)
ZOHO_BOOKINGS_CLIENT_ID=your_bookings_client_id
ZOHO_BOOKINGS_CLIENT_SECRET=your_bookings_client_secret
ZOHO_BOOKINGS_REFRESH_TOKEN=your_bookings_refresh_token

# Zoho WorkDrive (future - optional)
ZOHO_WORKDRIVE_CLIENT_ID=
ZOHO_WORKDRIVE_CLIENT_SECRET=
ZOHO_WORKDRIVE_REFRESH_TOKEN=

# Zoho Books (future - optional)
ZOHO_BOOKS_CLIENT_ID=
ZOHO_BOOKS_CLIENT_SECRET=
ZOHO_BOOKS_REFRESH_TOKEN=

# Zoho Mail (implemented)
ZOHO_MAIL_CLIENT_ID=1000.XXXXXXXXXXXXX
ZOHO_MAIL_CLIENT_SECRET=XXXXXXXXXXXXXXX
ZOHO_MAIL_REFRESH_TOKEN=1000.XXXXX.XXXXX
ZOHO_MAIL_REDIRECT_URI=https://platform.alfacrm.site/oauth/callback
ZOHO_MAIL_ACCOUNT_ID=4670982000000008002
```

### Interview Sync Logic
The interview sync determines status based on:
1. **Check_In_Status field** from Zoho Events:
   - "checked in" or "completed" → `status = "completed"`
   - "no show" or "absent" → `status = "no_show"`
   - "cancelled" → `status = "cancelled"`
2. **Date-based fallback** (if no Check_In_Status):
   - Event > 7 days old → `status = "completed"` (assumed)
   - Event < 7 days old and past → `status = "no_show"`
   - Future event → `status = "scheduled"`

**Known Issue**: Most Zoho Events don't have Check_In_Status populated, so many past events get marked as "no_show". The Zoho Bookings integration was intended to fix this by providing accurate attendance data, but is currently blocked by API issues.

### Field Mapping (Candidates)
Zoho `Lead_Status` is mapped to pipeline stages:

| Zoho Status | Platform Stage |
|-------------|----------------|
| New Candidate, LinkedIn Applicants, ZipRecruiter Leads | New Candidate |
| Screening, Pre-Qualified, Qualified | Screening |
| Interview Scheduled, Auto Interview - Invited | Interview Scheduled |
| Auto Interview - Done | Interview Completed |
| Language assessment assigned/to be graded | Assessment |
| Offer Accepted, Documents Downloaded, Training... | Onboarding |
| Tier 1, Tier 2, Tier 3 | Active |
| Lost Lead, Contact in Future | Inactive |
| Not Qualified, Junk Lead | Rejected |

---

## Database Configuration

### SQLite Optimizations
The database uses WAL mode and other optimizations for better concurrent access:

```python
# In app/core/database.py
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")      # Write-Ahead Logging
    cursor.execute("PRAGMA busy_timeout=30000")    # 30 second lock timeout
    cursor.execute("PRAGMA synchronous=NORMAL")    # Balance speed/safety
    cursor.close()
```

---

## Server Deployment

### Service Configuration
Location: `/etc/systemd/system/alfa-platform.service`

```ini
[Unit]
Description=Alfa AI Platform
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/alfa-platform
ExecStart=/opt/alfa-platform/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8003
Restart=always

[Install]
WantedBy=multi-user.target
```

### Common Commands
```bash
# Check status
systemctl status alfa-platform

# Restart service
systemctl restart alfa-platform

# View logs
journalctl -u alfa-platform -f

# Pull latest code
cd /opt/alfa-platform
git pull origin vibrant-solomon

# Install new dependencies
/opt/alfa-platform/venv/bin/pip install -r requirements.txt

# Trigger manual sync
curl -X POST http://localhost:8003/api/sync/candidates
curl -X POST http://localhost:8003/api/sync/interviews
```

### Database Location
- Path: `/opt/alfa-platform/data/alfa_platform.db`
- Type: SQLite with WAL mode

---

## Development

### Local Setup
```bash
# Clone repo
git clone https://github.com/vmsantos44/alfa-platform.git
cd alfa-platform
git checkout vibrant-solomon

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your Zoho credentials

# Run server
uvicorn app.main:app --reload --port 8003
```

### Key Files to Know
| File | Purpose |
|------|---------|
| `app/main.py` | App entry, page routes, lifespan |
| `app/config.py` | All environment variables and settings |
| `app/core/database.py` | SQLAlchemy setup, WAL mode config |
| `app/services/sync.py` | Zoho sync logic (candidates + interviews) |
| `app/services/scheduler.py` | Auto-sync scheduler |
| `app/routes/candidates.py` | Candidate API endpoints |
| `app/routes/interviews.py` | Interview API endpoints |
| `app/integrations/zoho/crm.py` | Zoho CRM API client |
| `app/integrations/zoho/mail.py` | Zoho Mail API client |
| `app/integrations/zoho/bookings.py` | Zoho Bookings API client |
| `app/routes/oauth.py` | OAuth authorization flow |
| `templates/scheduling.html` | Scheduling page with calendar |

---

## Known Issues & Pending Work

### 1. Zoho Bookings Integration (Blocked)
- **Issue**: API returns "EXECUTION ERROR :: Error setting value for the variable:'data' Invalid JSON Format String"
- **Attempted**: Changed from JSON to form-data, tried different scopes
- **Status**: Need to verify with Zoho CRM admin
- **Purpose**: Would provide accurate NO_SHOW/COMPLETED status instead of inferring from dates

### 2. Completion Rate Data Quality
- **Issue**: Completion rate may be inaccurate because Zoho Events often lack Check_In_Status
- **Current behavior**: Events without check-in status are marked as no-show if < 7 days old
- **Solution**: Either populate Check_In_Status in Zoho or complete Bookings integration

### 3. No-Show Count Migration
- **Issue**: Existing interviews have `no_show_count = 0` because previous sync didn't set it
- **Solution**: After deploying latest code, re-sync interviews to populate counts

---

## Future Enhancements

1. **Zoho Bookings Integration** - Complete integration for accurate attendance data
2. **Bulk Actions** - Multi-select candidates for bulk operations
3. **Notifications** - Email alerts for stuck candidates, upcoming interviews
4. **Documents Tab** - File upload/management via Zoho WorkDrive
5. **User Authentication** - Login system, role-based access
6. **AI Chat Assistant** - Integrated chat for operational assistance
7. **Billing Module** - Invoice and payment tracking via Zoho Books

---

## Troubleshooting

### Sync Not Working
1. Check Zoho OAuth tokens in environment
2. Test API: `curl http://localhost:8003/api/sync/scheduler/status`
3. Check logs: `journalctl -u alfa-platform -f`
4. Debug Zoho data: Visit `/api/sync/debug-zoho` or `/api/sync/debug-events`

### Database Issues
1. Database location: `/opt/alfa-platform/data/alfa_platform.db`
2. Backup: `cp alfa_platform.db alfa_platform.db.backup`
3. Check WAL files: `ls -la data/` (should see .db, .db-wal, .db-shm)
4. Reset: Delete DB file, restart service (tables auto-create)

### Database Locked Errors
1. WAL mode should prevent most issues
2. Check for long-running queries
3. Increase busy_timeout if needed (currently 30 seconds)

### Service Won't Start
1. Check syntax: `python -m py_compile app/main.py`
2. Check dependencies: `/opt/alfa-platform/venv/bin/pip install -r requirements.txt`
3. Check logs: `journalctl -u alfa-platform --no-pager -n 50`

### High No-Show Numbers
1. This is expected behavior due to sync logic
2. Events without Check_In_Status are marked as no-show
3. To fix: Either update Check_In_Status in Zoho or complete Bookings integration

---

## Recent Changes (December 2025)

### Zoho Mail Integration (NEW)
- Full OAuth 2.0 flow with `/oauth/authorize` and `/oauth/callback`
- Zoho Mail API client (`app/integrations/zoho/mail.py`)
- API endpoints for:
  - Test connection (`/api/mail/test`)
  - List folders (`/api/mail/folders`)
  - Get/search emails (`/api/mail/emails`, `/api/mail/search`)
  - Contact email history (`/api/mail/contact/{email}`)
  - Send emails (`/api/mail/send`)
- Auto token refresh with 60-second buffer
- Retry logic with exponential backoff

### Interview Sync
- Added `sync_interviews_from_zoho()` in sync.py
- Syncs from Zoho CRM Events module
- Identifies interviews by keywords in event title
- Sets status based on Check_In_Status or date

### Scheduling Page UI
- Stats cards with icons and colored borders
- Today's Interviews with better card design
- No-Shows section with filtering (7/30/90 days)
- Pagination with "Load More"
- Scrollable containers

### Database Improvements
- SQLite WAL mode for concurrent access
- 30-second busy timeout
- Connection health checks

### Zoho Multi-Client Architecture
- Config supports separate OAuth credentials per Zoho product
- **Mail client implemented and working**
- Bookings client implemented (API issues pending)
- Ready for WorkDrive, Books integration

---

## Contact

For questions about this codebase, refer to:
- GitHub Issues: https://github.com/vmsantos44/alfa-platform/issues
- Code comments and docstrings throughout the codebase

---

*Last Updated: December 1, 2025*
