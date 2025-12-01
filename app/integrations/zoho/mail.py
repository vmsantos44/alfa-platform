"""
Alfa AI Platform - Zoho Mail Integration
Send and receive emails via Zoho Mail API
"""
import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_settings


# Retry decorator for API calls
mail_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
)


class ZohoMailOAuth:
    """Manages Zoho Mail OAuth tokens"""

    def __init__(self):
        self.settings = get_settings()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._lock = asyncio.Lock()

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary"""
        async with self._lock:
            now = datetime.now().timestamp()

            # Refresh if token expires in less than 60 seconds
            if self._access_token and self._token_expires_at > (now + 60):
                return self._access_token

            # Refresh the token
            await self._refresh_token()
            return self._access_token

    async def _refresh_token(self):
        """Refresh the access token using refresh token"""
        if not self.settings.zoho_mail_refresh_token:
            raise Exception("ZOHO_MAIL_REFRESH_TOKEN not configured. Visit /oauth/authorize first.")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.settings.zoho_accounts_domain}/oauth/v2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.settings.zoho_mail_client_id,
                    "client_secret": self.settings.zoho_mail_client_secret,
                    "refresh_token": self.settings.zoho_mail_refresh_token,
                }
            )

            data = response.json()

            if "error" in data:
                raise Exception(f"Token refresh failed: {data.get('error_description', data.get('error'))}")

            self._access_token = data["access_token"]
            self._token_expires_at = datetime.now().timestamp() + data.get("expires_in", 3600)
            print(f"🔄 Zoho Mail token refreshed, expires in {data.get('expires_in')}s")


# Global OAuth instance
_mail_oauth: Optional[ZohoMailOAuth] = None


def get_mail_oauth() -> ZohoMailOAuth:
    """Get the global Zoho Mail OAuth instance"""
    global _mail_oauth
    if _mail_oauth is None:
        _mail_oauth = ZohoMailOAuth()
    return _mail_oauth


class ZohoMailAPI:
    """Zoho Mail API client for sending and receiving emails"""

    def __init__(self):
        self.settings = get_settings()
        self.oauth = get_mail_oauth()
        self.client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10)
        )

    async def _get_headers(self) -> Dict[str, str]:
        """Get headers with valid access token"""
        token = await self.oauth.get_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json"
        }

    @property
    def account_id(self) -> str:
        """Get the configured account ID"""
        if not self.settings.zoho_mail_account_id:
            raise Exception("ZOHO_MAIL_ACCOUNT_ID not configured. Visit /oauth/authorize to get it.")
        return self.settings.zoho_mail_account_id

    @mail_retry
    async def get_accounts(self) -> Dict[str, Any]:
        """Get all mail accounts"""
        headers = await self._get_headers()
        response = await self.client.get(
            f"{self.settings.zoho_mail_api_url}/accounts",
            headers=headers
        )
        response.raise_for_status()
        return response.json()

    @mail_retry
    async def get_folders(self) -> Dict[str, Any]:
        """Get all folders (inbox, sent, etc.)"""
        headers = await self._get_headers()
        response = await self.client.get(
            f"{self.settings.zoho_mail_api_url}/accounts/{self.account_id}/folders",
            headers=headers
        )
        response.raise_for_status()
        return response.json()

    @mail_retry
    async def get_emails(
        self,
        folder_id: Optional[str] = None,
        limit: int = 50,
        start: int = 0,
        sort_by: str = "date",
        sort_order: str = "desc"
    ) -> Dict[str, Any]:
        """
        Get emails from a folder

        Args:
            folder_id: Folder ID (if None, gets from inbox)
            limit: Number of emails to fetch (max 200)
            start: Offset for pagination
            sort_by: Sort field (date, subject, from)
            sort_order: asc or desc
        """
        headers = await self._get_headers()

        # If no folder_id, get inbox folder first
        if not folder_id:
            folders = await self.get_folders()
            for folder in folders.get("data", []):
                if folder.get("folderName", "").lower() == "inbox":
                    folder_id = folder.get("folderId")
                    break

        if not folder_id:
            raise Exception("Could not find inbox folder")

        params = {
            "folderId": folder_id,
            "limit": min(limit, 200),
            "start": start,
            "includeto": "true",
        }

        response = await self.client.get(
            f"{self.settings.zoho_mail_api_url}/accounts/{self.account_id}/messages/view",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        return response.json()

    @mail_retry
    async def get_email(self, message_id: str) -> Dict[str, Any]:
        """Get a specific email by ID"""
        headers = await self._get_headers()
        response = await self.client.get(
            f"{self.settings.zoho_mail_api_url}/accounts/{self.account_id}/messages/{message_id}",
            headers=headers
        )
        response.raise_for_status()
        return response.json()

    @mail_retry
    async def get_email_content(self, message_id: str) -> Dict[str, Any]:
        """Get the full content of an email"""
        headers = await self._get_headers()
        response = await self.client.get(
            f"{self.settings.zoho_mail_api_url}/accounts/{self.account_id}/messages/{message_id}/content",
            headers=headers
        )
        response.raise_for_status()
        return response.json()

    @mail_retry
    async def search_emails(
        self,
        query: str,
        limit: int = 50,
        start: int = 0
    ) -> Dict[str, Any]:
        """
        Search emails

        Args:
            query: Search query (e.g., "from:john@example.com", "subject:meeting")
            limit: Number of results
            start: Offset for pagination
        """
        headers = await self._get_headers()

        params = {
            "searchKey": query,
            "limit": min(limit, 200),
            "start": start
        }

        response = await self.client.get(
            f"{self.settings.zoho_mail_api_url}/accounts/{self.account_id}/messages/search",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        return response.json()

    @mail_retry
    async def send_email(
        self,
        to: List[str],
        subject: str,
        content: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        from_address: Optional[str] = None,
        is_html: bool = True
    ) -> Dict[str, Any]:
        """
        Send an email

        Args:
            to: List of recipient email addresses
            subject: Email subject
            content: Email body (HTML or plain text)
            cc: List of CC recipients
            bcc: List of BCC recipients
            from_address: From address (uses default if not specified)
            is_html: Whether content is HTML
        """
        headers = await self._get_headers()

        email_data = {
            "toAddress": ",".join(to),
            "subject": subject,
            "content": content,
            "mailFormat": "html" if is_html else "plaintext"
        }

        if from_address:
            email_data["fromAddress"] = from_address

        if cc:
            email_data["ccAddress"] = ",".join(cc)

        if bcc:
            email_data["bccAddress"] = ",".join(bcc)

        response = await self.client.post(
            f"{self.settings.zoho_mail_api_url}/accounts/{self.account_id}/messages",
            headers=headers,
            json=email_data
        )
        response.raise_for_status()
        return response.json()

    @mail_retry
    async def get_emails_by_contact(
        self,
        email_address: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get all emails sent to/from a specific email address
        Useful for showing email history on a contact profile

        Args:
            email_address: The contact's email address
            limit: Number of emails to fetch
        """
        # Search for emails from this address
        from_results = await self.search_emails(
            query=f"from:{email_address}",
            limit=limit
        )

        # Search for emails to this address
        to_results = await self.search_emails(
            query=f"to:{email_address}",
            limit=limit
        )

        # Combine and deduplicate
        all_emails = {}

        for email in from_results.get("data", []):
            msg_id = email.get("messageId")
            if msg_id:
                email["direction"] = "received"
                all_emails[msg_id] = email

        for email in to_results.get("data", []):
            msg_id = email.get("messageId")
            if msg_id and msg_id not in all_emails:
                email["direction"] = "sent"
                all_emails[msg_id] = email

        # Sort by date descending
        sorted_emails = sorted(
            all_emails.values(),
            key=lambda x: x.get("receivedTime", 0),
            reverse=True
        )

        return {
            "data": sorted_emails[:limit],
            "count": len(sorted_emails)
        }

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


# Global API instance
_mail_api: Optional[ZohoMailAPI] = None
_mail_api_lock = asyncio.Lock()


async def get_mail_api() -> ZohoMailAPI:
    """Get the global Zoho Mail API instance"""
    global _mail_api
    async with _mail_api_lock:
        if _mail_api is None:
            _mail_api = ZohoMailAPI()
        return _mail_api


# Convenience functions
async def send_email(
    to: List[str],
    subject: str,
    content: str,
    **kwargs
) -> Dict[str, Any]:
    """Send an email"""
    api = await get_mail_api()
    return await api.send_email(to, subject, content, **kwargs)


async def get_emails(limit: int = 50, **kwargs) -> Dict[str, Any]:
    """Get emails from inbox"""
    api = await get_mail_api()
    return await api.get_emails(limit=limit, **kwargs)


async def get_contact_emails(email_address: str, limit: int = 50) -> Dict[str, Any]:
    """Get all emails for a contact (sent and received)"""
    api = await get_mail_api()
    return await api.get_emails_by_contact(email_address, limit=limit)


async def search_emails(query: str, limit: int = 50) -> Dict[str, Any]:
    """Search emails"""
    api = await get_mail_api()
    return await api.search_emails(query, limit=limit)
