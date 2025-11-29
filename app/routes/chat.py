"""
Chat router - AI assistant endpoints
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def chat_root():
    """Chat endpoint placeholder"""
    return {"message": "Chat API - Coming soon"}
