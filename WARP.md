# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Alfa AI Platform is a unified FastAPI application that integrates Zoho CRM services with AI capabilities. The platform provides a web interface for CRM operations and AI-assisted workflows, primarily focused on candidate/contact management and recruitment operations.

## Development Commands

### Running the Application

```bash
# Start the development server (with auto-reload)
python app/main.py

# Or using uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Production mode (no reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Environment Setup

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template and configure
cp .env .env  # Then edit with actual credentials
```

### Testing

Currently, there is no test suite in place. When writing tests, consider:
- Creating test files in the `tests/` directory
- Using pytest as the testing framework (aligned with dependency ecosystem)
- Testing async functions with pytest-asyncio

## Architecture

### High-Level Structure

The application follows a layered FastAPI architecture:

```
app/
├── main.py              # FastAPI app entry point, CORS, router mounting
├── config.py            # Centralized settings using Pydantic Settings
├── core/                # Core shared utilities
│   └── oauth.py         # Zoho OAuth singleton manager
├── routes/              # API endpoints
│   ├── api.py           # General API routes (placeholder)
│   ├── chat.py          # AI chat endpoints (placeholder)
│   └── webhooks.py      # External webhook receivers (placeholder)
├── integrations/        # External service integrations
│   ├── zoho/
│   │   └── crm.py       # Zoho CRM client (dual-mode: OAuth + proxy API)
│   └── microsoft/       # Microsoft Teams (future, empty)
├── features/            # Business logic modules (empty)
└── models/              # Pydantic models (empty)
```

### Dual CRM Access Pattern

The Zoho CRM integration (`app/integrations/zoho/crm.py`) implements a **dual-access pattern**:

1. **Direct Zoho API (OAuth 2.0)**: `ZohoAPI` class
   - Direct API calls to `zohoapis.com`
   - OAuth token management with automatic refresh
   - Used for: basic CRUD, search, email sending, attachments
   - Thread-safe with asyncio locks

2. **CRM Proxy API (alfacrm.site)**: Helper functions
   - Proxy service at `alfacrm.site` with API key auth
   - Used for: advanced features, candidate operations, bulk operations
   - Fallback logic to try multiple CRM modules (Contacts → Leads → Vendors, etc.)

**Key Functions:**
- `search_contact()`, `search_lead()`: Search via proxy API
- `get_record()`: Fetch record with module fallback logic
- `get_notes()`, `get_communications()`, `list_attachments()`: Fetch related data
- `lookup_candidate()`: Smart search + full profile fetching
- `get_candidate_full_profile()`: Comprehensive candidate data aggregation
- `create_note()`, `create_task()`, `send_email()`, `send_sms()`: Create operations

### OAuth Token Management

Centralized in `app/core/oauth.py` as a **singleton** (`zoho_oauth`):
- Auto-refreshes tokens before expiry (60s buffer)
- Thread-safe with asyncio lock
- Caches access token to minimize refresh requests
- Used across all Zoho product APIs (CRM, Books, Mail, WorkDrive)

### Configuration Pattern

All settings in `app/config.py` use **Pydantic Settings**:
- Loads from `.env` file automatically
- Type validation and defaults
- Feature flags for optional integrations (Books, Mail, WorkDrive, Teams)
- Access via `get_settings()` cached singleton or legacy `settings` object

### API Routes

Routes are organized by domain:
- `/health`: Health check endpoint
- `/chat/*`: AI chat interface (placeholder)
- `/api/*`: General API endpoints (placeholder)
- `/webhooks/*`: Webhook receivers (placeholder)
- `/`: Static files (Chat UI) - mounted last to catch remaining paths

## Key Technical Patterns

### Async-First Design
All I/O operations are async (httpx, FastAPI). Use `async/await` throughout.

### Retry Logic with Tenacity
The CRM module uses `@api_retry` decorator for transient failures:
- 3 attempts max
- Exponential backoff (1-10 seconds)
- Retries on: timeouts, connection errors, 5xx errors, 429 rate limits

### Connection Pooling
HTTP clients use connection pools to prevent resource exhaustion:
```python
limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
client = httpx.AsyncClient(timeout=30.0, limits=limits)
```

### Module Fallback Logic
CRM operations implement smart fallback:
- Try requested module first (e.g., "Contacts")
- If not found, try other modules (Leads, Vendors, Deals, Accounts)
- Return result from first successful module
- Used in: `get_record()`, `get_notes()`, `get_communications()`, `list_attachments()`

### Singleton Pattern for Shared Resources
- `zoho_oauth`: OAuth manager
- `ZohoAPI`: Global API client instance via `get_zoho_api()`
- `get_client()`: HTTP client for CRM proxy API

## Important Implementation Notes

### Environment Variables
- All credentials must be in `.env` (never hardcoded)
- `ZOHO_ORG_ID` is hardcoded to `815230494` in CRM module
- Feature flags control optional integrations (default: disabled)

### Error Handling
- HTTP errors return `{"success": False, "error": "..."}` dicts
- CRM functions gracefully handle 204/404 as empty results
- Always check `result.get("success")` before accessing data

### CRM Record URLs
Use `get_crm_record_url(module, record_id)` to generate direct Zoho CRM links:
```python
url = get_crm_record_url("Contacts", "123456789012345678")
# Returns: https://crm.zoho.com/crm/org815230494/tab/Contacts/123456789012345678
```

### Candidate Operations
Candidate-specific functions expect contact data with fields:
- `stage`: Candidate stage in recruitment pipeline
- `assigned_client`: Client assignment
- `tier`: Tier classification
- `languages`: Language capabilities
- Use `lookup_candidate()` for smart search + auto-profile fetching

## Project-Specific Conventions

### Import Style
- Absolute imports: `from app.config import get_settings`
- No relative imports: avoid `from ..config import ...`

### Logging
- Use `print()` for operational logging (no structured logging yet)
- Emoji prefixes for readability: 🚀 (startup), 🔄 (refresh), ✅ (success), ❌ (error), 📍 (discovery)

### Async Context Managers
Use lifespan events in `main.py` for startup/shutdown logic:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
```

### Static File Serving
The `/` route is mounted LAST to serve static files (HTML, CSS, JS) as a catch-all. All API routes must be mounted before this.

## Future Integrations (Placeholders)

These are stubbed but not implemented:
- **Zoho Books**: Accounting/invoicing (feature flag: `ENABLE_BOOKS`)
- **Zoho Mail**: Email management (feature flag: `ENABLE_MAIL`)
- **Zoho WorkDrive**: Document storage (feature flag: `ENABLE_WORKDRIVE`, partial implementation exists)
- **Microsoft Teams**: Notifications (feature flag: `ENABLE_TEAMS`)
- **AI Chat**: OpenAI integration planned but routes are placeholders

## Critical Dependencies

- **FastAPI 0.104.1**: Web framework
- **httpx 0.25.2**: Async HTTP client (replaces requests)
- **tenacity 8.2.3**: Retry logic
- **openai 1.3.0**: AI capabilities (not yet integrated)
- **pydantic 2.5.0**: Data validation and settings
- **uvicorn 0.24.0**: ASGI server

## Notes for AI Agents

- When adding new Zoho API calls, use the `ZohoAPI` class in `crm.py` and add retry decorators
- When adding new routes, register them in `main.py` with `app.include_router()`
- When adding new settings, update `app/config.py` Settings class and `.env`
- The CRM proxy API (alfacrm.site) is external; treat it as a black box
- Always use async/await for I/O operations
- Connection pooling is already configured; reuse existing clients
