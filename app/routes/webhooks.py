"""
Webhooks router - External service webhooks
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def webhooks_root():
    """Webhooks endpoint placeholder"""
    return {"message": "Webhooks - Coming soon"}
