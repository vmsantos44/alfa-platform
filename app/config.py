"""
Alfa AI Platform - Configuration
All settings loaded from environment variables
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings"""

    # Use absolute path for .env file (works regardless of working directory)
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Base directory
    base_dir: Path = Path(__file__).resolve().parent.parent
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    
    # Zoho Organization
    zoho_org_id: str = "815230494"
    zoho_accounts_domain: str = "https://accounts.zoho.com"
    zoho_api_domain: str = "https://www.zohoapis.com"

    # Zoho CRM OAuth (primary - also used as fallback for other products)
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_crm_api_url: str = "https://www.zohoapis.com/crm"
    zoho_from_email: str = ""

    # Zoho Bookings OAuth (separate client for booking/scheduling)
    zoho_bookings_client_id: str = ""
    zoho_bookings_client_secret: str = ""
    zoho_bookings_refresh_token: str = ""

    # Zoho WorkDrive OAuth (separate client for document storage)
    zoho_workdrive_client_id: str = ""
    zoho_workdrive_client_secret: str = ""
    zoho_workdrive_refresh_token: str = ""
    zoho_workdrive_api_url: str = "https://www.zohoapis.com/workdrive"

    # Zoho Books OAuth (separate client for accounting)
    zoho_books_client_id: str = ""
    zoho_books_client_secret: str = ""
    zoho_books_refresh_token: str = ""
    zoho_books_api_url: str = "https://www.zohoapis.com/books"

    # Zoho Mail OAuth (separate client for email)
    zoho_mail_client_id: str = ""
    zoho_mail_client_secret: str = ""
    zoho_mail_refresh_token: str = ""
    zoho_mail_redirect_uri: str = "http://localhost:8003/oauth/callback"
    zoho_mail_account_id: str = ""
    zoho_mail_api_url: str = "https://mail.zoho.com/api"
    
    # CRM API proxy (alfacrm.site)
    crm_api_url: str = ""
    crm_api_key: str = ""
    
    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    
    # Microsoft Teams (for future use)
    teams_tenant_id: str = ""
    teams_client_id: str = ""
    teams_client_secret: str = ""
    teams_webhook_url: str = ""
    
    # Feature flags
    enable_books: bool = False
    enable_mail: bool = False
    enable_workdrive: bool = False
    enable_teams: bool = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Legacy exports for backward compatibility
settings = get_settings()
HOST = settings.host
PORT = settings.port
DEBUG = settings.debug
