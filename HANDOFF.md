# Alfa Operations Platform - Handoff Document

## Project Overview

**Alfa Operations Platform** is a unified operations dashboard for interpreter recruitment. It syncs candidate data from Zoho CRM and provides a streamlined interface for managing the recruitment pipeline.

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
| Task Scheduler | APScheduler |
| Charts | Chart.js |
| Server | Ubuntu with systemd |

---

## Features Implemented

### 1. Zoho CRM Sync
- Syncs candidates from Zoho CRM Leads module
- Maps Zoho `Lead_Status` to 9 pipeline stages
- Auto-sync every 30 minutes (configurable)
- Manual sync trigger available

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

### 6. Auto-Sync Scheduler
- Configurable interval (5 min to 24 hours)
- Start/Stop from Settings page
- Shows next sync time, last sync results
- Prevents overlapping syncs

---

## Project Structure

```
alfa-platform/
├── app/
│   ├── main.py                 # FastAPI app, routes, lifespan
│   ├── config.py               # Environment configuration
│   ├── core/
│   │   └── database.py         # SQLAlchemy async setup
│   ├── models/
│   │   ├── database_models.py  # SQLAlchemy models
│   │   └── schemas.py          # Pydantic schemas
│   ├── routes/
│   │   ├── candidates.py       # Candidate CRUD, pipeline, notes
│   │   ├── dashboard.py        # Dashboard stats, analytics
│   │   ├── sync.py             # Sync + scheduler endpoints
│   │   ├── interviews.py       # Interview management
│   │   └── ...
│   ├── services/
│   │   ├── sync.py             # Zoho sync logic
│   │   └── scheduler.py        # APScheduler service
│   └── integrations/
│       └── zoho/
│           ├── auth.py         # OAuth 2.0 token management
│           └── crm.py          # Zoho CRM API client
├── templates/
│   ├── base.html               # Base layout with sidebar
│   ├── dashboard.html          # Dashboard with charts
│   ├── candidates.html         # Pipeline/list views
│   ├── candidate_detail.html   # Full candidate profile
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

### Interview, Task, ActionAlert, SyncLog
Supporting tables for scheduling, tasks, alerts, and sync tracking.

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

### Sync & Scheduler
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sync/scheduler/status` | Get scheduler status |
| POST | `/api/sync/scheduler/start` | Start auto-sync |
| POST | `/api/sync/scheduler/stop` | Stop auto-sync |
| POST | `/api/sync/scheduler/trigger` | Trigger sync now |
| PUT | `/api/sync/scheduler/interval` | Update sync interval |
| POST | `/api/sync/candidates` | Manual sync (legacy) |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard/stats` | Dashboard statistics |
| GET | `/api/dashboard/analytics/pipeline-funnel` | Funnel data |
| GET | `/api/dashboard/analytics/by-language` | Language breakdown |
| GET | `/api/dashboard/analytics/by-tier` | Tier breakdown |
| GET | `/api/dashboard/analytics/by-owner` | Owner breakdown |
| GET | `/api/dashboard/analytics/recent-activity` | Recent activity |

---

## Zoho CRM Integration

### Authentication
- OAuth 2.0 with refresh token
- Tokens stored in environment variables
- Auto-refresh on expiry

### Environment Variables
```env
ZOHO_CLIENT_ID=your_client_id
ZOHO_CLIENT_SECRET=your_client_secret
ZOHO_REFRESH_TOKEN=your_refresh_token
ZOHO_REDIRECT_URI=https://platform.alfacrm.site/oauth/callback
```

### Field Mapping
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
```

### Database Location
- Path: `/opt/alfa-platform/data/alfa_platform.db`
- Type: SQLite

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
| `app/services/sync.py` | Zoho sync logic, status mapping |
| `app/services/scheduler.py` | Auto-sync scheduler |
| `app/routes/candidates.py` | All candidate API endpoints |
| `templates/candidates.html` | Pipeline/list views |
| `templates/candidate_detail.html` | Candidate profile page |
| `templates/settings.html` | Settings + sync controls |

---

## Future Enhancements

1. **Scheduling Module** - Interview calendar, training calendar
2. **Reports Module** - CSV/Excel export, pipeline metrics
3. **Bulk Actions** - Multi-select candidates for bulk operations
4. **Notifications** - Email alerts for stuck candidates, upcoming interviews
5. **Documents Tab** - File upload/management
6. **User Authentication** - Login system, role-based access

---

## Troubleshooting

### Sync Not Working
1. Check Zoho OAuth tokens in environment
2. Test API: `curl http://localhost:8003/api/sync/scheduler/status`
3. Check logs: `journalctl -u alfa-platform -f`

### Database Issues
1. Database location: `/opt/alfa-platform/data/alfa_platform.db`
2. Backup: `cp alfa_platform.db alfa_platform.db.backup`
3. Reset: Delete DB file, restart service (tables auto-create)

### Service Won't Start
1. Check syntax: `python -m py_compile app/main.py`
2. Check dependencies: `/opt/alfa-platform/venv/bin/pip install -r requirements.txt`
3. Check logs: `journalctl -u alfa-platform --no-pager -n 50`

---

## Contact

For questions about this codebase, refer to:
- GitHub Issues: https://github.com/vmsantos44/alfa-platform/issues
- Code comments and docstrings throughout the codebase

---

*Last Updated: November 30, 2025*
