"""
Alfa AI Platform - Zoho OAuth Manager
Unified token management for all Zoho products
"""
import httpx
import time
import asyncio
from typing import Optional, Dict
from app.config import (
    ZOHO_CLIENT_ID, 
    ZOHO_CLIENT_SECRET, 
    ZOHO_REFRESH_TOKEN,
    ZOHO_ACCOUNTS_URL
)


class ZohoOAuth:
    """
    Singleton OAuth manager for all Zoho products.
    
    Features:
    - Automatic token refresh
    - Token caching (avoid unnecessary refreshes)
    - Thread-safe with asyncio lock
    - Rate limit awareness
    """
    
    def __init__(self):
        self.client_id = ZOHO_CLIENT_ID
        self.client_secret = ZOHO_CLIENT_SECRET
        self.refresh_token = ZOHO_REFRESH_TOKEN
        self.access_token: Optional[str] = None
        self.token_expiry: float = 0
        self._lock = asyncio.Lock()
        
    async def get_access_token(self) -> str:
        """
        Get valid access token, refreshing if needed.
        Thread-safe with asyncio lock.
        """
        async with self._lock:
            # Check if current token is still valid (with 60s buffer)
            if self.access_token and time.time() < self.token_expiry - 60:
                return self.access_token
            
            # Refresh token
            await self._refresh_token()
            return self.access_token
    
    async def _refresh_token(self):
        """Refresh the access token from Zoho"""
        print("🔄 Refreshing Zoho access token...")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token",
                data={
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token"
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if "access_token" not in data:
                raise Exception(f"Token refresh failed: {data}")
            
            self.access_token = data["access_token"]
            # Default to 1 hour if not specified
            self.token_expiry = time.time() + data.get("expires_in", 3600)
            print(f"✅ Token refreshed, expires in {data.get('expires_in', 3600)}s")
    
    async def get_headers(self) -> Dict[str, str]:
        """Get headers with valid auth token for API calls"""
        token = await self.get_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json"
        }


# Singleton instance - import this in other modules
zoho_oauth = ZohoOAuth()
