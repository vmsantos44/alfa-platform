"""
API router - CRM and integration endpoints
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def api_root():
    """API endpoint placeholder"""
    return {"message": "API - Coming soon"}
