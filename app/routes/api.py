"""
API router - CRM and integration endpoints
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.config import get_settings
from app.integrations.zoho.mail import (
    get_mail_api,
    send_email,
    get_contact_emails,
    search_emails
)

router = APIRouter()


@router.get("/")
async def api_root():
    """API endpoint placeholder"""
    return {"message": "API - Coming soon"}


# ======================
# ZOHO MAIL ENDPOINTS
# ======================

@router.get("/mail/test")
async def test_mail_connection():
    """Test the Zoho Mail connection"""
    settings = get_settings()

    if not settings.zoho_mail_refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Zoho Mail not configured. Visit /oauth/authorize to set up."
        )

    try:
        api = await get_mail_api()
        accounts = await api.get_accounts()
        return {
            "status": "connected",
            "accounts": accounts.get("data", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail/folders")
async def list_folders():
    """Get all mail folders"""
    try:
        api = await get_mail_api()
        return await api.get_folders()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail/emails")
async def list_emails(
    limit: int = Query(50, ge=1, le=200),
    start: int = Query(0, ge=0),
    folder_id: Optional[str] = None
):
    """Get emails from inbox or specified folder"""
    try:
        api = await get_mail_api()
        return await api.get_emails(folder_id=folder_id, limit=limit, start=start)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail/emails/{message_id}")
async def get_email_detail(message_id: str):
    """Get a specific email with full content"""
    try:
        api = await get_mail_api()
        email = await api.get_email(message_id)
        content = await api.get_email_content(message_id)
        return {
            "email": email,
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail/search")
async def search_mail(
    q: str = Query(..., description="Search query (e.g., 'from:john@example.com')"),
    limit: int = Query(50, ge=1, le=200)
):
    """Search emails"""
    try:
        return await search_emails(q, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail/contact/{email_address}")
async def get_contact_email_history(
    email_address: str,
    limit: int = Query(50, ge=1, le=200)
):
    """
    Get all emails sent to/from a specific email address.
    Useful for showing email history on a contact profile.
    """
    try:
        return await get_contact_emails(email_address, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mail/send")
async def send_mail(
    to: List[str],
    subject: str,
    content: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    is_html: bool = True
):
    """Send an email"""
    try:
        result = await send_email(
            to=to,
            subject=subject,
            content=content,
            cc=cc,
            bcc=bcc,
            is_html=is_html
        )
        return {"status": "sent", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
