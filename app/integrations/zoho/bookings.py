"""
Zoho Bookings Integration - Separate OAuth client for booking/scheduling

This module uses its own OAuth credentials to access Zoho Bookings API,
providing accurate appointment status (COMPLETED, NO_SHOW, CANCEL, etc.)
"""
import asyncio
import httpx
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from app.config import get_settings
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


# Reusable retry decorator for API calls
api_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)


class ZohoBookingsAPI:
    """
    Zoho Bookings API client with its own OAuth token management.

    Uses separate credentials from CRM for better security and isolation.
    Falls back to CRM credentials if Bookings-specific credentials not configured.
    """

    # Booking status constants
    STATUS_UPCOMING = "UPCOMING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_NO_SHOW = "NO_SHOW"
    STATUS_CANCEL = "CANCEL"
    STATUS_ONGOING = "ONGOING"
    STATUS_PENDING = "PENDING"
    STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
    STATUS_PAYMENT_FAILURE = "PAYMENT_FAILURE"

    def __init__(self):
        self.settings = get_settings()
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[float] = None
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=10)
        self.client = httpx.AsyncClient(timeout=30.0, limits=limits)
        self._token_lock = asyncio.Lock()

        # Use Bookings-specific credentials if available, otherwise fall back to CRM
        self.client_id = self.settings.zoho_bookings_client_id or self.settings.zoho_client_id
        self.client_secret = self.settings.zoho_bookings_client_secret or self.settings.zoho_client_secret
        self.refresh_token = self.settings.zoho_bookings_refresh_token or self.settings.zoho_refresh_token

        if not self.refresh_token:
            print("⚠️ ZohoBookingsAPI: No refresh token configured")

    def is_configured(self) -> bool:
        """Check if Bookings API credentials are configured"""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def has_dedicated_credentials(self) -> bool:
        """Check if using dedicated Bookings credentials (not CRM fallback)"""
        return bool(self.settings.zoho_bookings_refresh_token)

    async def get_access_token(self) -> str:
        """Get access token, refreshing if necessary"""
        if self.access_token and self.token_expiry and time.time() < self.token_expiry:
            return self.access_token

        async with self._token_lock:
            if self.access_token and self.token_expiry and time.time() < self.token_expiry:
                return self.access_token

            try:
                response = await self.client.post(
                    f"{self.settings.zoho_accounts_domain}/oauth/v2/token",
                    params={
                        "refresh_token": self.refresh_token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "refresh_token",
                    },
                )
                response.raise_for_status()

                data = response.json()
                self.access_token = data["access_token"]
                self.token_expiry = time.time() + (55 * 60)

                print("🔄 ZohoBookingsAPI: Token refreshed successfully")
                return self.access_token
            except httpx.HTTPError as e:
                raise Exception(f"Failed to authenticate with Zoho Bookings: {str(e)}")

    async def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        token = await self.get_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    @api_retry
    async def fetch_appointments(
        self,
        from_date: datetime,
        to_date: datetime,
        status: Optional[str] = None,
        service_id: Optional[str] = None,
        staff_id: Optional[str] = None,
        page: int = 1,
        per_page: int = 50
    ) -> Dict[str, Any]:
        """
        Fetch appointments from Zoho Bookings.

        Args:
            from_date: Start date for appointments
            to_date: End date for appointments
            status: Filter by status (UPCOMING, COMPLETED, NO_SHOW, CANCEL, etc.)
            service_id: Filter by service
            staff_id: Filter by staff member
            page: Page number
            per_page: Results per page (max 50)

        Returns:
            Dict with appointments data and pagination info
        """
        headers = await self._get_headers()

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
        if service_id:
            payload["service_id"] = service_id
        if staff_id:
            payload["staff_id"] = staff_id

        try:
            response = await self.client.post(
                f"{self.settings.zoho_api_domain}/bookings/v1/json/fetchappointment",
                headers=headers,
                data=payload  # Form-data, not JSON
            )

            if response.status_code == 204:
                return {"appointments": [], "next_page_available": False}

            response.raise_for_status()
            data = response.json()

            # Normalize response structure
            appointments = []
            if "response" in data:
                return_value = data.get("response", {}).get("returnvalue", {})
                if isinstance(return_value, dict):
                    appointments = return_value.get("data", [])
                elif isinstance(return_value, list):
                    appointments = return_value

            return {
                "appointments": appointments,
                "next_page_available": data.get("next_page_available", False),
                "raw": data
            }
        except httpx.HTTPError as e:
            error_detail = ""
            if hasattr(e, 'response') and e.response:
                error_detail = e.response.text[:500] if e.response.text else ""
            raise Exception(f"Failed to fetch bookings: {str(e)} - {error_detail}")

    @api_retry
    async def get_appointment(self, booking_id: str) -> Dict[str, Any]:
        """
        Get a specific appointment by booking ID.

        Args:
            booking_id: The booking ID (e.g., RE-12727)

        Returns:
            Dict with appointment details
        """
        headers = await self._get_headers()

        try:
            response = await self.client.post(
                f"{self.settings.zoho_api_domain}/bookings/v1/json/getappointment",
                headers=headers,
                data={"booking_id": booking_id}  # Form-data, not JSON
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"Failed to get booking {booking_id}: {str(e)}")

    async def fetch_all_appointments(
        self,
        from_date: datetime,
        to_date: datetime,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch all appointments with automatic pagination.

        Args:
            from_date: Start date
            to_date: End date
            status: Optional status filter

        Returns:
            List of all appointments
        """
        all_appointments = []
        page = 1

        while True:
            result = await self.fetch_appointments(
                from_date=from_date,
                to_date=to_date,
                status=status,
                page=page,
                per_page=50
            )

            appointments = result.get("appointments", [])
            all_appointments.extend(appointments)

            if not result.get("next_page_available", False):
                break

            page += 1

            # Safety limit
            if page > 100:
                print("⚠️ ZohoBookingsAPI: Reached pagination limit (100 pages)")
                break

        return all_appointments

    async def get_no_shows(
        self,
        from_date: datetime,
        to_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Get all NO_SHOW appointments in date range.
        """
        return await self.fetch_all_appointments(
            from_date=from_date,
            to_date=to_date,
            status=self.STATUS_NO_SHOW
        )

    async def get_completed(
        self,
        from_date: datetime,
        to_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Get all COMPLETED appointments in date range.
        """
        return await self.fetch_all_appointments(
            from_date=from_date,
            to_date=to_date,
            status=self.STATUS_COMPLETED
        )

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


# Global instance
_bookings_instance: Optional[ZohoBookingsAPI] = None
_bookings_lock = asyncio.Lock()


async def get_zoho_bookings() -> ZohoBookingsAPI:
    """Get or create global Zoho Bookings API instance"""
    global _bookings_instance
    if _bookings_instance is None:
        async with _bookings_lock:
            if _bookings_instance is None:
                _bookings_instance = ZohoBookingsAPI()
    return _bookings_instance
