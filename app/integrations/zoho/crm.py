"""
Zoho CRM Integration - Combined API client with OAuth 2.0 authentication

Combines functionality from:
- alfa-ai-console/app/services/crm_service.py (CRM operations via alfacrm.site API)
- zoho-crm-python/app/api/zoho_api.py (Direct Zoho API with OAuth)
"""
import asyncio
import httpx
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from app.config import get_settings
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


# ============================================================================
# CONFIGURATION
# ============================================================================

settings = get_settings()
ZOHO_ORG_ID = "815230494"


# ============================================================================
# RETRY LOGIC
# ============================================================================

def is_retryable_error(exception: BaseException) -> bool:
    """Determine if an exception is retryable (transient network issues)"""
    if isinstance(exception, httpx.TimeoutException):
        return True
    if isinstance(exception, httpx.ConnectError):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        # Retry on 5xx server errors and 429 rate limit
        return exception.response.status_code >= 500 or exception.response.status_code == 429
    return False


# Reusable retry decorator for API calls
api_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)


# ============================================================================
# ZOHO API CLIENT (Direct OAuth-based access)
# ============================================================================

class ZohoAPI:
    """Zoho CRM API client with automatic token refresh"""

    def __init__(self):
        self.settings = get_settings()
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[float] = None
        # Connection pool limits to prevent resource exhaustion
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        self.client = httpx.AsyncClient(timeout=30.0, limits=limits)
        self._token_lock = asyncio.Lock()

    async def get_access_token(self) -> str:
        """Get access token, refreshing if necessary"""
        # Quick check without lock for performance
        if self.access_token and self.token_expiry and time.time() < self.token_expiry:
            return self.access_token

        # Acquire lock for token refresh to prevent race conditions
        async with self._token_lock:
            # Double-check after acquiring lock (another coroutine may have refreshed)
            if self.access_token and self.token_expiry and time.time() < self.token_expiry:
                return self.access_token

            # Get new access token using refresh token
            try:
                response = await self.client.post(
                    f"{self.settings.zoho_accounts_domain}/oauth/v2/token",
                    params={
                        "refresh_token": self.settings.zoho_refresh_token,
                        "client_id": self.settings.zoho_client_id,
                        "client_secret": self.settings.zoho_client_secret,
                        "grant_type": "refresh_token",
                    },
                )
                response.raise_for_status()

                data = response.json()
                self.access_token = data["access_token"]
                # Set expiry to 55 minutes (tokens last 1 hour, refresh early)
                self.token_expiry = time.time() + (55 * 60)

                return self.access_token
            except httpx.HTTPError as e:
                raise Exception(f"Failed to authenticate with Zoho: {str(e)}")

    async def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        token = await self.get_access_token()
        return {"Authorization": f"Zoho-oauthtoken {token}"}

    @api_retry
    async def get_records(
        self,
        module: str,
        page: int = 1,
        per_page: int = 200,
        fields: Optional[List[str]] = None,
        criteria: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get records from a Zoho CRM module with pagination.

        Args:
            module: CRM module name (Leads, Contacts, etc.)
            page: Page number (starts at 1)
            per_page: Records per page (max 200)
            fields: Optional list of field names to retrieve
            criteria: Optional COQL criteria string

        Returns:
            Dict with 'data' list and 'info' pagination details
        """
        headers = await self._get_headers()

        params = {
            "page": page,
            "per_page": min(per_page, 200)
        }

        if fields:
            params["fields"] = ",".join(fields)

        try:
            if criteria:
                # Use search API with criteria
                response = await self.client.get(
                    f"{self.settings.zoho_api_domain}/crm/v2/{module}/search",
                    headers=headers,
                    params={"criteria": criteria, **params},
                )
            else:
                # Use regular get records API
                response = await self.client.get(
                    f"{self.settings.zoho_api_domain}/crm/v2/{module}",
                    headers=headers,
                    params=params,
                )

            # Handle 204 No Content (no records)
            if response.status_code == 204:
                return {"data": [], "info": {"more_records": False}}

            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            if hasattr(e, 'response') and e.response and e.response.status_code == 204:
                return {"data": [], "info": {"more_records": False}}
            raise Exception(f"Failed to get records from {module}: {str(e)}")

    @api_retry
    async def search_contacts(self, search_term: str) -> Dict[str, Any]:
        """Search for contacts by name or email"""
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/Contacts/search",
                headers=headers,
                params={
                    "criteria": f"(First_Name:equals:{search_term})or(Last_Name:equals:{search_term})or(Email:equals:{search_term})"
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"Failed to search contacts: {str(e)}")

    @api_retry
    async def search_leads(self, search_term: str) -> Dict[str, Any]:
        """Search for leads by name or email"""
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/Leads/search",
                headers=headers,
                params={
                    "criteria": f"(First_Name:equals:{search_term})or(Last_Name:equals:{search_term})or(Email:equals:{search_term})"
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"Failed to search leads: {str(e)}")

    @api_retry
    async def get_record(self, module: str, record_id: str) -> Dict[str, Any]:
        """Get a specific record by ID"""
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/{module}/{record_id}",
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"Failed to get record: {str(e)}")

    @api_retry
    async def get_notes(self, module: str, record_id: str) -> Dict[str, Any]:
        """Get all notes for a record"""
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/{module}/{record_id}/Notes",
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"Failed to get notes: {str(e)}")

    @api_retry
    async def get_all_notes(
        self,
        page: int = 1,
        per_page: int = 200,
        modified_since: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get all notes from Zoho CRM Notes module.

        Args:
            page: Page number (starts at 1)
            per_page: Records per page (max 200)
            modified_since: ISO timestamp to fetch only notes modified after this time
                           Format: 2024-01-01T00:00:00+00:00

        Returns:
            Dict with 'data' list and 'info' pagination details
        """
        headers = await self._get_headers()

        # Add If-Modified-Since header for incremental sync
        if modified_since:
            headers["If-Modified-Since"] = modified_since

        params = {
            "page": page,
            "per_page": min(per_page, 200),
            "fields": "id,Note_Title,Note_Content,Parent_Id,$se_module,Owner,Created_Time,Modified_Time"
        }

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/Notes",
                headers=headers,
                params=params,
            )

            # Handle 204 No Content (no records) or 304 Not Modified
            if response.status_code in (204, 304):
                return {"data": [], "info": {"more_records": False}}

            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            if hasattr(e, "response") and e.response.status_code in (204, 304):
                return {"data": [], "info": {"more_records": False}}
            raise Exception(f"Failed to get all notes: {str(e)}")

    @api_retry
    async def get_activities(self, module: str, record_id: str) -> Dict[str, Any]:
        """Get all activities (emails, calls, tasks, events) for a record"""
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/{module}/{record_id}/Activities",
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            # Handle 204 No Content or 404 Not Found
            if hasattr(e, "response") and e.response.status_code in (204, 404):
                return {"data": []}
            raise Exception(f"Failed to get activities: {str(e)}")

    @api_retry
    async def get_emails_for_record(
        self,
        module: str,
        record_id: str,
        page: int = 1,
        per_page: int = 100
    ) -> Dict[str, Any]:
        """
        Get emails for a specific record from Zoho CRM.

        Args:
            module: CRM module (Leads, Contacts, etc.)
            record_id: The record ID
            page: Page number (starts at 1)
            per_page: Records per page (max 200)

        Returns:
            Dict with 'data' list of emails and 'info' pagination details
        """
        headers = await self._get_headers()

        params = {
            "page": page,
            "per_page": min(per_page, 200)
        }

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/{module}/{record_id}/Emails",
                headers=headers,
                params=params,
            )

            # Handle 204 No Content (no emails)
            if response.status_code == 204:
                return {"data": [], "info": {"more_records": False}}

            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            if hasattr(e, "response") and e.response:
                if e.response.status_code in (204, 404):
                    return {"data": [], "info": {"more_records": False}}
            raise Exception(f"Failed to get emails for {module}/{record_id}: {str(e)}")

    @api_retry
    async def get_email_content(
        self,
        module: str,
        record_id: str,
        message_id: str
    ) -> Dict[str, Any]:
        """
        Get full content of a single email from Zoho CRM.

        Args:
            module: CRM module (Leads, Contacts, etc.)
            record_id: The record ID
            message_id: The email message ID

        Returns:
            Dict with email details including 'content' (HTML body)
        """
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/{module}/{record_id}/Emails/{message_id}",
                headers=headers,
            )

            # Handle 204 No Content
            if response.status_code == 204:
                return {}

            response.raise_for_status()
            data = response.json()

            # Zoho returns the email in 'Emails' array
            emails = data.get("Emails", [])
            return emails[0] if emails else data

        except httpx.HTTPError as e:
            if hasattr(e, "response") and e.response:
                if e.response.status_code in (204, 404):
                    return {}
            raise Exception(f"Failed to get email content: {str(e)}")

    @api_retry
    async def get_attachments(self, module: str, record_id: str) -> Dict[str, Any]:
        """List all attachments for a record"""
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/{module}/{record_id}/Attachments",
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            # Handle 204 No Content or 404 Not Found
            if hasattr(e, "response") and e.response.status_code in (204, 404):
                return {"data": []}
            raise Exception(f"Failed to get attachments: {str(e)}")

    @api_retry
    async def download_attachment(
        self, module: str, record_id: str, attachment_id: str
    ) -> bytes:
        """Download a specific attachment"""
        headers = await self._get_headers()

        try:
            response = await self.client.get(
                f"{self.settings.zoho_api_domain}/crm/v2/{module}/{record_id}/Attachments/{attachment_id}",
                headers=headers,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            raise Exception(f"Failed to download attachment: {str(e)}")

    @api_retry
    async def send_email(
        self,
        to_address: str,
        subject: str,
        body: str,
        from_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email via Zoho CRM"""
        headers = await self._get_headers()
        headers["Content-Type"] = "application/json"

        email_data = {
            "from": {"user_name": from_address or self.settings.zoho_from_email},
            "to": [{"email": to_address}],
            "subject": subject,
            "content": body,
        }

        try:
            response = await self.client.post(
                f"{self.settings.zoho_api_domain}/crm/v2/Emails/actions/send",
                headers=headers,
                json=email_data,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"Failed to send email: {str(e)}")

    # =========================================================================
    # ZOHO BOOKINGS API
    # =========================================================================

    @api_retry
    async def get_bookings(
        self,
        from_date: datetime,
        to_date: datetime,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 50
    ) -> Dict[str, Any]:
        """
        Fetch appointments from Zoho Bookings.

        Args:
            from_date: Start date for appointments
            to_date: End date for appointments
            status: Filter by status (UPCOMING, COMPLETED, NO_SHOW, CANCEL, etc.)
            page: Page number
            per_page: Results per page (max 50)

        Returns:
            Dict with bookings data and pagination info

        Status values: UPCOMING, CANCEL, ONGOING, PENDING, COMPLETED,
                      NO_SHOW, PENDING_PAYMENT, PAYMENT_FAILURE
        """
        headers = await self._get_headers()
        headers["Content-Type"] = "application/json"

        # Format dates as expected by Zoho Bookings API: dd-MMM-yyyy
        from_str = from_date.strftime("%d-%b-%Y")
        to_str = to_date.strftime("%d-%b-%Y")

        payload = {
            "from_time": from_str,
            "to_time": to_str,
            "page": page,
            "per_page": min(per_page, 50)
        }

        if status:
            payload["status"] = status

        try:
            response = await self.client.post(
                f"{self.settings.zoho_api_domain}/bookings/v1/json/fetchappointment",
                headers=headers,
                json=payload
            )

            # Handle 204 No Content
            if response.status_code == 204:
                return {"response": {"returnvalue": {"data": []}}, "next_page_available": False}

            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            if hasattr(e, 'response') and e.response:
                error_text = e.response.text[:500] if e.response.text else ""
                raise Exception(f"Failed to fetch bookings: {str(e)} - {error_text}")
            raise Exception(f"Failed to fetch bookings: {str(e)}")

    @api_retry
    async def get_booking_by_id(self, booking_id: str) -> Dict[str, Any]:
        """
        Get a specific booking/appointment by ID.

        Args:
            booking_id: The booking ID (e.g., RE-12727)

        Returns:
            Dict with booking details
        """
        headers = await self._get_headers()
        headers["Content-Type"] = "application/json"

        try:
            response = await self.client.post(
                f"{self.settings.zoho_api_domain}/bookings/v1/json/getappointment",
                headers=headers,
                json={"booking_id": booking_id}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"Failed to get booking {booking_id}: {str(e)}")

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


# Global API client instance
_api_instance: Optional[ZohoAPI] = None
_api_lock = asyncio.Lock()


async def get_zoho_api() -> ZohoAPI:
    """Get or create global Zoho API instance (singleton pattern with lock)"""
    global _api_instance
    if _api_instance is None:
        async with _api_lock:
            # Double-check after acquiring lock
            if _api_instance is None:
                _api_instance = ZohoAPI()
    return _api_instance


# ============================================================================
# CRM SERVICE (Via alfacrm.site proxy - for advanced features)
# ============================================================================

# HTTP client instance (reuse connection pool)
_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Get or create HTTP client for CRM API proxy"""
    global _client
    if _client is None:
        headers = {}
        if settings.crm_api_key:
            headers["X-API-Key"] = settings.crm_api_key
        _client = httpx.AsyncClient(
            base_url=settings.crm_api_url,
            timeout=30.0,
            headers=headers
        )
    return _client


async def close_client():
    """Close HTTP client and release connections"""
    global _client
    if _client:
        await _client.aclose()
        _client = None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_crm_record_url(module: str, record_id: str) -> str:
    """Generate the direct URL to a CRM record"""
    return f"https://crm.zoho.com/crm/org{ZOHO_ORG_ID}/tab/{module}/{record_id}"


# ============================================================================
# SEARCH OPERATIONS
# ============================================================================

async def search_contact(
    search_term: str,
    limit: int = 10,
    intelligent: bool = True
) -> dict:
    """
    Search for contacts by name or email.
    
    Args:
        search_term: Name or email to search for
        limit: Maximum number of results (1-200)
        intelligent: Include AI recommendations
    
    Returns:
        dict with 'success', 'data', 'count', 'total'
    """
    client = get_client()
    try:
        response = await client.get(
            "/api/search-contact",
            params={
                "searchTerm": search_term,
                "limit": min(limit, 200),
                "intelligent": intelligent,
            }
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "success": False,
            "error": f"CRM API error: {str(e)}",
            "data": []
        }


async def search_lead(
    search_term: str,
    limit: int = 10,
    intelligent: bool = True
) -> dict:
    """
    Search for leads by name or email.
    
    Args:
        search_term: Name or email to search for
        limit: Maximum number of results (1-200)
        intelligent: Include AI recommendations
    
    Returns:
        dict with 'success', 'data', 'count', 'total'
    """
    client = get_client()
    try:
        response = await client.get(
            "/api/search-lead",
            params={
                "searchTerm": search_term,
                "limit": min(limit, 200),
                "intelligent": intelligent,
            }
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "success": False,
            "error": f"CRM API error: {str(e)}",
            "data": []
        }


# ============================================================================
# RECORD OPERATIONS
# ============================================================================

async def get_record(module: str, record_id: str, try_other_modules: bool = True) -> dict:
    """
    Get complete record details.
    
    Args:
        module: CRM module (Contacts, Leads, Deals, Accounts, Vendors)
        record_id: Record ID
        try_other_modules: If True, try other modules if the specified one fails
    
    Returns:
        dict with full record data
    """
    client = get_client()
    
    # Modules to try in order
    modules_to_try = [module]
    if try_other_modules:
        all_modules = ["Contacts", "Leads", "Vendors", "Deals", "Accounts"]
        modules_to_try = [module] + [m for m in all_modules if m != module]
    
    last_error = None
    for try_module in modules_to_try:
        try:
            response = await client.get(
                "/api/get-record",
                params={"module": try_module, "recordId": record_id}
            )
            response.raise_for_status()
            result = response.json()
            if result.get("success", False):
                # Add module info to result
                result["_module"] = try_module
                if try_module != module:
                    print(f"📍 Found record in {try_module} (originally searched {module})")
                return result
        except httpx.HTTPError as e:
            last_error = str(e)
            if try_other_modules:
                continue  # Try next module
            else:
                break
    
    return {
        "success": False,
        "error": f"CRM API error: {last_error or 'Record not found in any module'}"
    }


async def get_notes(module: str, record_id: str, try_other_modules: bool = True) -> dict:
    """
    Get all notes for a record.
    
    Args:
        module: CRM module
        record_id: Record ID
        try_other_modules: If True, try other modules if the specified one has no notes
    
    Returns:
        dict with notes data
    """
    client = get_client()
    
    # Try primary module first
    print(f"📝 Fetching notes for {module} record {record_id}")
    try:
        response = await client.post(
            "/api/get-notes",
            json={"module": module, "record_id": record_id}
        )
        response.raise_for_status()
        result = response.json()
        
        notes_list = result.get("notes", [])
        notes_count = result.get("count", len(notes_list))
        
        print(f"📝 {module} returned {notes_count} notes")
        
        # If we found notes in primary module, return immediately
        if notes_count > 0:
            result["found_in"] = module
            return result
            
    except httpx.HTTPError as e:
        error_text = ""
        if hasattr(e, 'response') and e.response:
            error_text = e.response.text
        print(f"❌ Notes fetch error for {module}: {str(e)} {error_text[:100]}")
    
    # No notes in primary module - should we try others?
    if not try_other_modules:
        return {
            "success": True,
            "notes": [],
            "count": 0,
            "found_in": module,
            "message": f"No notes found for this {module.rstrip('s')} record"
        }
    
    # Try fallback modules
    all_modules = ["Contacts", "Leads", "Vendors", "Deals", "Accounts"]
    fallback_modules = [m for m in all_modules if m != module]
    
    print(f"⚠️ No notes in {module}, checking other modules...")
    
    for fallback_module in fallback_modules:
        # First verify the record exists in this module
        record_exists = await _record_exists_in_module(fallback_module, record_id)
        
        if not record_exists:
            continue
        
        print(f"✅ Record exists in {fallback_module}, fetching notes...")
        
        try:
            response = await client.post(
                "/api/get-notes",
                json={"module": fallback_module, "record_id": record_id}
            )
            response.raise_for_status()
            result = response.json()
            
            notes_list = result.get("notes", [])
            notes_count = result.get("count", len(notes_list))
            
            print(f"📝 {fallback_module} returned {notes_count} notes")
            print(f"📍 Record is in {fallback_module} (originally searched {module})")
            
            result["found_in"] = fallback_module
            result["original_module"] = module
            result["message"] = f"Record found in {fallback_module}, not {module}"
            return result
            
        except httpx.HTTPError as e:
            error_text = ""
            if hasattr(e, 'response') and e.response:
                error_text = e.response.text
            print(f"❌ Notes fetch error for {fallback_module}: {str(e)} {error_text[:100]}")
            continue
    
    # Record doesn't exist in any fallback module
    print(f"❌ Record not found in any other module")
    return {
        "success": True,
        "notes": [],
        "count": 0,
        "found_in": module,
        "message": f"No notes found for this record"
    }


async def _record_exists_in_module(module: str, record_id: str) -> bool:
    """
    Check if a record exists in the specified module.
    """
    client = get_client()
    try:
        response = await client.get(
            "/api/get-record",
            params={"module": module, "recordId": record_id}
        )
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False)
        return False
    except Exception as e:
        print(f"⚠️ Record check failed for {module}/{record_id}: {str(e)}")
        return False


async def get_communications(module: str, record_id: str, try_other_modules: bool = True) -> dict:
    """
    Get all communications for a record (emails, calls, tasks, events).
    
    Args:
        module: CRM module (Contacts, Leads, etc.)
        record_id: Record ID
        try_other_modules: If True, try other modules if the specified one fails
    
    Returns:
        dict with communications data
    """
    client = get_client()
    
    # Modules to try in order
    modules_to_try = [module]
    if try_other_modules:
        all_modules = ["Contacts", "Leads", "Vendors", "Deals", "Accounts"]
        modules_to_try = [module] + [m for m in all_modules if m != module]
    
    last_error = None
    best_result = None
    best_count = -1
    
    print(f"🔍 get_communications: Trying modules in order: {modules_to_try}")
    
    for try_module in modules_to_try:
        try:
            print(f"🔍 get_communications: Trying {try_module}/{record_id}")
            response = await client.post(
                "/api/get-communications",
                json={"module": try_module, "record_id": record_id}
            )
            response.raise_for_status()
            result = response.json()
            if result.get("success", False):
                total_communications = result.get("count", {}).get("total", 0)
                print(f"✅ get_communications: {try_module} returned {total_communications} total communications")
                # Track the result with the most communications
                if total_communications > best_count:
                    best_count = total_communications
                    best_result = result
                    if try_module != module:
                        best_result["_module_used"] = try_module
                        best_result["_module_requested"] = module
                # If we found communications, return immediately
                if total_communications > 0:
                    print(f"✅ get_communications: Found communications in {try_module}, returning immediately")
                    return best_result
            else:
                print(f"⚠️ get_communications: {try_module} returned success=False: {result.get('error', 'Unknown error')}")
        except httpx.HTTPError as e:
            last_error = e
            print(f"❌ get_communications: {try_module} failed with HTTP error: {str(e)}")
            continue
    
    # Return the best result found (even if 0 communications) or error
    if best_result:
        return best_result
    
    return {
        "success": False,
        "error": f"CRM API error: {str(last_error)}" if last_error else "Failed to fetch communications from any module"
    }


async def list_attachments(module: str, record_id: str, try_other_modules: bool = True) -> dict:
    """
    List all attachments/documents for a record.
    
    Args:
        module: CRM module
        record_id: Record ID
        try_other_modules: If True, try other modules if the specified one fails
    
    Returns:
        dict with attachments list including file_name, size, created_time
    """
    client = get_client()
    
    # Modules to try in order
    modules_to_try = [module]
    if try_other_modules:
        all_modules = ["Contacts", "Leads", "Vendors", "Deals", "Accounts"]
        modules_to_try = [module] + [m for m in all_modules if m != module]
    
    last_error = None
    best_result = None
    
    for try_module in modules_to_try:
        try:
            print(f"📎 Fetching attachments for {try_module} record {record_id}")
            response = await client.post(
                "/api/list-attachments",
                json={"module": try_module, "record_id": record_id}
            )
            response.raise_for_status()
            result = response.json()
            
            attachments_list = result.get("attachments", [])
            attachments_count = result.get("count", len(attachments_list))
            
            print(f"📎 {try_module} returned {attachments_count} attachments")
            
            # If we found attachments, return immediately
            if attachments_count > 0:
                if try_module != module:
                    print(f"📍 Found {attachments_count} attachments in {try_module} (originally searched {module})")
                    result["_module_used"] = try_module
                return result
            
            # Keep track of first successful (but empty) result
            if best_result is None and result.get("success", True):
                best_result = result
                
            # Continue to try other modules
            print(f"⚠️ No attachments in {try_module}, trying next module...")
            continue
                
        except httpx.HTTPError as e:
            last_error = e
            error_text = ""
            if hasattr(e, 'response') and e.response:
                error_text = e.response.text
            print(f"❌ Attachments fetch error for {try_module}: {str(e)} {error_text[:100]}")
            continue
    
    # Return best result we found, or error
    if best_result:
        return best_result
        
    return {
        "success": False,
        "error": f"CRM API error: {str(last_error)}" if last_error else "Attachments not found",
        "attachments": []
    }


# ============================================================================
# CREATE OPERATIONS
# ============================================================================

async def send_email(
    to_address: str,
    subject: str,
    body: str,
    from_address: Optional[str] = None
) -> dict:
    """
    Send an email via Zoho CRM.
    
    Args:
        to_address: Recipient email
        subject: Email subject
        body: Email body
        from_address: Optional sender email
    
    Returns:
        dict with success status
    """
    client = get_client()
    payload = {
        "toAddress": to_address,
        "subject": subject,
        "body": body
    }
    if from_address:
        payload["fromAddress"] = from_address
    
    try:
        response = await client.post("/api/send-email", json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "success": False,
            "error": f"CRM API error: {str(e)}"
        }


async def create_task(
    subject: str,
    module: str,
    record_id: str,
    due_date: Optional[str] = None,
    priority: str = "Normal",
    status: str = "Not Started",
    description: Optional[str] = None
) -> dict:
    """
    Create a task in Zoho CRM.
    
    Args:
        subject: Task subject
        module: CRM module
        record_id: Record ID to link task to
        due_date: Optional due date (YYYY-MM-DD)
        priority: Task priority (Normal, High, Low)
        status: Task status (Not Started, In Progress, Completed)
        description: Optional task description
    
    Returns:
        dict with success status and task ID
    """
    client = get_client()
    payload = {
        "subject": subject,
        "module": module,
        "recordId": record_id,
        "priority": priority,
        "status": status
    }
    if due_date:
        payload["dueDate"] = due_date
    if description:
        payload["description"] = description
    
    try:
        response = await client.post("/api/create-task", json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "success": False,
            "error": f"CRM API error: {str(e)}"
        }


async def create_note(
    module: str,
    record_id: str,
    title: str,
    content: str
) -> dict:
    """
    Create a note on a CRM record.
    
    Args:
        module: CRM module (Contacts, Leads, etc.)
        record_id: Record ID to attach the note to
        title: Note title/subject
        content: Note content/body
    
    Returns:
        dict with success status and note ID
    """
    client = get_client()
    try:
        response = await client.post(
            "/api/create-note",
            json={
                "module": module,
                "record_id": record_id,
                "title": title,
                "content": content
            }
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "success": False,
            "error": f"CRM API error: {str(e)}"
        }


async def send_sms(
    to_number: str,
    message: str,
    record_id: Optional[str] = None,
    module: Optional[str] = None
) -> dict:
    """
    Send an SMS via Twilio.
    
    Args:
        to_number: Phone number to send to
        message: SMS message content
        record_id: Optional CRM record ID for logging
        module: Optional CRM module (Contacts, Leads, Vendors)
    
    Returns:
        dict with success status and message_sid
    """
    client = get_client()
    payload = {
        "to_number": to_number,
        "message": message
    }
    if record_id:
        payload["record_id"] = record_id
    if module:
        payload["module"] = module
    
    try:
        response = await client.post("/api/send-sms", json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "success": False,
            "error": f"SMS API error: {str(e)}"
        }


# ============================================================================
# CANDIDATE-SPECIFIC OPERATIONS
# ============================================================================

async def get_candidates_for_sidebar(
    recruiter_email: Optional[str] = None,
    stage: Optional[str] = None,
    assigned_client: Optional[str] = None,
    tier: Optional[str] = None,
    search_term: Optional[str] = None,
    page: int = 1,
    limit: int = 50
) -> dict:
    """
    Get candidates for the sidebar panel using field-based CRM filtering.
    
    Args:
        recruiter_email: Email of the recruiter (filters by Candidate_Recruitment_Owner)
        stage: Optional stage filter
        assigned_client: Optional client filter
        tier: Optional tier filter
        search_term: Optional search by name or email
        page: Page number for pagination
        limit: Results per page (max: 200)
    
    Returns:
        dict with candidates list, engagement levels, and status indicators
    """
    client = get_client()
    candidates = []
    
    # Build query parameters
    params = {"limit": min(limit * 2, 200)}
    
    # Add filters
    if recruiter_email:
        params["recruitment_owner"] = recruiter_email
    if stage:
        params["stage"] = stage
    if assigned_client:
        params["assigned_client"] = assigned_client
    if tier:
        params["tier"] = tier
    if search_term:
        params["search"] = search_term
    
    # Ensure we have at least one filter besides limit
    if len(params) <= 1:
        return {
            "candidates": [],
            "total": 0,
            "page": page,
            "limit": limit,
            "has_more": False,
            "filters_applied": {
                "stage": stage,
                "assigned_client": assigned_client,
                "tier": tier,
                "search": search_term
            }
        }
    
    try:
        response = await client.get("/api/list-candidates", params=params)
        response.raise_for_status()
        result = response.json()
        
        if result.get("success") and result.get("candidates"):
            for record in result["candidates"]:
                candidate = _process_candidate_for_sidebar(record)
                candidates.append(candidate)
    
    except Exception as e:
        print(f"Error fetching candidates: {str(e)}")
        return {
            "candidates": [],
            "total": 0,
            "page": page,
            "limit": limit,
            "has_more": False,
            "filters_applied": {
                "stage": stage,
                "assigned_client": assigned_client,
                "tier": tier,
                "search": search_term
            },
            "error": str(e)
        }
    
    # Apply pagination to results
    total = len(candidates)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_candidates = candidates[start_idx:end_idx]
    
    return {
        "candidates": paginated_candidates,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": end_idx < total,
        "filters_applied": {
            "stage": stage,
            "assigned_client": assigned_client,
            "tier": tier,
            "search": search_term
        }
    }


def _process_candidate_for_sidebar(record: dict) -> dict:
    """Process a candidate record for sidebar display"""
    candidate_id = record.get("id")
    
    # Basic info
    candidate = {
        "id": candidate_id,
        "module": record.get("module", "Contacts"),
        "name": record.get("name", "Unknown"),
        "email": record.get("email", ""),
        "stage": record.get("stage", ""),
        "assigned_client": record.get("assigned_client", ""),
        "tier": record.get("tier", ""),
        "languages": record.get("languages", ""),
        "last_communication_date": record.get("last_activity"),
        "engagement": "low",
        "missing_documents": [],
        "status_indicators": []
    }
    
    # Check if unresponsive based on last activity
    if candidate["last_communication_date"]:
        try:
            last_date = datetime.fromisoformat(candidate["last_communication_date"].replace("Z", "+00:00"))
            days_since = (datetime.now(last_date.tzinfo) - last_date).days
            if days_since >= 7:
                candidate["status_indicators"].append("unresponsive")
            # Estimate engagement from days since last activity
            if days_since <= 3:
                candidate["engagement"] = "high"
            elif days_since <= 7:
                candidate["engagement"] = "medium"
        except:
            pass
    
    # Check training requirement
    assigned_client = record.get("assigned_client", "")
    tier = record.get("tier", "")
    if assigned_client == "Cloudbreak" or tier in ["Tier 2", "Tier 3"]:
        candidate["status_indicators"].append("training_required")
    
    # Check credentials pending
    stage = record.get("stage", "")
    if stage in ["Training Required (Client/Tier)", "Credentials Ordered (Interpreter)"]:
        candidate["status_indicators"].append("credentials_pending")
    
    return candidate


async def get_candidate_full_profile(identifier: str, module: str = "Contacts") -> dict:
    """
    Get complete candidate profile including record, notes, communications, and attachments.
    
    Args:
        identifier: Record ID to look up
        module: Starting module to search (Contacts or Leads), defaults to Contacts
    
    Returns:
        dict with complete profile data
    """
    print(f"👤 Getting full profile for {identifier} (starting with {module})")
    
    # Step 1: Get the record and determine correct module
    record_result = await get_record(module, identifier, try_other_modules=True)
    
    if not record_result.get("success"):
        return {
            "success": False,
            "error": "Candidate not found in any module",
            "identifier": identifier
        }
    
    # Use the actual module where record was found
    actual_module = record_result.get("_module", module)
    print(f"📍 Record found in {actual_module}")
    
    # Step 2: Fetch all related data using the correct module
    notes_result = await get_notes(actual_module, identifier, try_other_modules=False)
    communications_result = await get_communications(actual_module, identifier, try_other_modules=False)
    attachments_result = await list_attachments(actual_module, identifier, try_other_modules=False)
    
    # Step 3: Compile the full profile
    profile = {
        "success": True,
        "module": actual_module,
        "record_id": identifier,
        "crm_url": get_crm_record_url(actual_module, identifier),
        "record": record_result,
        "notes": {
            "count": notes_result.get("count", len(notes_result.get("notes", []))),
            "items": notes_result.get("notes", [])
        },
        "communications": {
            "count": communications_result.get("count", {}).get("total", 0),
            "emails": communications_result.get("emails", []),
            "calls": communications_result.get("calls", []),
            "tasks": communications_result.get("tasks", []),
            "events": communications_result.get("events", [])
        },
        "attachments": {
            "count": attachments_result.get("count", len(attachments_result.get("attachments", []))),
            "items": attachments_result.get("attachments", [])
        }
    }
    
    print(f"✅ Full profile compiled: {profile['notes']['count']} notes, {profile['communications']['count']} communications, {profile['attachments']['count']} attachments")
    
    return profile


async def lookup_candidate(search_term: str) -> dict:
    """
    Smart candidate lookup - searches AND gets full profile in ONE call.
    
    Args:
        search_term: Name, email, or ID to search for
    
    Returns:
        dict with either full profile OR list of matches to choose from
    """
    print(f"🔍 Smart lookup for: {search_term}")
    
    # Check if search_term looks like a record ID
    if search_term.replace(" ", "").isdigit() and len(search_term.replace(" ", "")) >= 16:
        print(f"📍 Detected record ID, fetching full profile directly")
        return await get_candidate_full_profile(search_term.strip(), "Contacts")
    
    # Search both modules
    contacts_result = await search_contact(search_term, limit=10)
    leads_result = await search_lead(search_term, limit=10)
    
    # Combine results
    all_results = []
    
    if contacts_result.get("success"):
        for record in contacts_result.get("data", []):
            all_results.append({
                "id": record.get("id"),
                "name": record.get("Full_Name", "Unknown"),
                "email": record.get("Email", ""),
                "phone": record.get("Phone", ""),
                "stage": record.get("Stage", record.get("Candidate_Stage", "")),
                "module": "Contacts"
            })
    
    if leads_result.get("success"):
        for record in leads_result.get("data", []):
            all_results.append({
                "id": record.get("id"),
                "name": record.get("Full_Name", "Unknown"),
                "email": record.get("Email", ""),
                "phone": record.get("Phone", ""),
                "stage": record.get("Stage", record.get("Candidate_Stage", "")),
                "module": "Leads"
            })
    
    print(f"📊 Found {len(all_results)} total results")
    
    # No results
    if not all_results:
        return {
            "success": False,
            "message": f"No candidates found matching '{search_term}'. Try searching by email or check the spelling."
        }
    
    # Check for exact name match
    search_lower = search_term.lower().strip()
    exact_matches = [r for r in all_results if r["name"].lower() == search_lower]
    
    # If exactly one exact match, get full profile
    if len(exact_matches) == 1:
        match = exact_matches[0]
        print(f"✅ Exact match found: {match['name']} in {match['module']}")
        profile = await get_candidate_full_profile(match["id"], match["module"])
        profile["matched_by"] = "exact_name"
        return profile
    
    # If only one result total, get full profile
    if len(all_results) == 1:
        match = all_results[0]
        print(f"✅ Single result found: {match['name']} in {match['module']}")
        profile = await get_candidate_full_profile(match["id"], match["module"])
        profile["matched_by"] = "single_result"
        return profile
    
    # Check if search term matches email exactly
    email_matches = [r for r in all_results if r["email"].lower() == search_lower]
    if len(email_matches) == 1:
        match = email_matches[0]
        print(f"✅ Exact email match found: {match['name']} in {match['module']}")
        profile = await get_candidate_full_profile(match["id"], match["module"])
        profile["matched_by"] = "exact_email"
        return profile
    
    # Multiple matches - return list for user to choose
    print(f"🔢 Multiple matches ({len(all_results)}), returning list for selection")
    
    # Add CRM URL to each candidate
    candidates_with_urls = [
        {**c, "crm_url": get_crm_record_url(c["module"], c["id"])} 
        for c in all_results
    ]
    
    return {
        "success": True,
        "multiple_matches": True,
        "count": len(all_results),
        "candidates": candidates_with_urls,
        "message": f"Found {len(all_results)} candidates matching '{search_term}'. Please specify which one by name or ID."
    }


# ============================================================================
# WORKDRIVE
# ============================================================================

async def workdrive_search(query: str, parent_id: Optional[str] = None, limit: int = 20) -> dict:
    """
    Search Zoho WorkDrive for documents.

    Args:
        query: Search keyword
        parent_id: Optional folder ID to scope search
        limit: Maximum results (1-200)

    Returns:
        dict with search results
    """
    client = get_client()
    params = {"query": query, "limit": min(limit, 200)}
    if parent_id:
        params["parentId"] = parent_id

    try:
        response = await client.get("/api/workdrive-search", params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "success": False,
            "error": f"CRM API error: {str(e)}"
        }


# ============================================================================
# ALIAS FOR BACKWARD COMPATIBILITY
# ============================================================================

# ZohoCRM is an alias for ZohoAPI (used by sync service)
ZohoCRM = ZohoAPI
