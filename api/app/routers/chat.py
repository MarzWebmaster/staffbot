"""Chat router — proxies to Server B gateway with enforcement."""
import os, httpx, json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.middleware.auth import get_current_client
from app.models.client import Client
from app.services.enforcement_service import EnforcementService

router = APIRouter()

SERVER_B_URL = os.environ.get("STAFFBOT_SERVER_B_API_URL", "http://69.161.221.104:8080")
SERVER_B_KEY = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")


class ChatSendRequest(BaseModel):
    content: str
    container_id: Optional[int] = None
    provider: str = "openrouter"
    model: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/send")
async def chat_send(
    data: ChatSendRequest,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message with enforcement applied."""
    # Step 1: Get enforcement rules
    enforcement = await EnforcementService.get_enforcement(
        client_id=current_user.id,
        db=db,
    )

    # Step 2: Build context with enforcement info
    system_context = {
        "client_id": current_user.id,
        "client_name": current_user.name or "",
        "client_company": current_user.company or "",
        "client_package": current_user.package or "basic",
        "enforcement": {
            "allowed_skills": enforcement.get("allowed_skill_ids", []),
            "allowed_tools": enforcement.get("allowed_tool_ids", []),
            "governance": enforcement.get("governance", {}),
            "token_quota": enforcement.get("token", {}).get("quota", 0),
            "token_used": enforcement.get("token", {}).get("used", 0),
        },
    }

    # Step 3: Proxy to Server B with enforcement context
    headers = {
        "Content-Type": "application/json",
        "x-api-key": SERVER_B_KEY,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{SERVER_B_URL}/api/chat/send",
            json={
                "client_id": current_user.id,
                "container_id": data.container_id,
                "content": data.content,
                "provider": data.provider,
                "model": data.model,
                "api_key": data.api_key,
                "system_context": system_context,
            },
            headers=headers,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()


@router.get("/history")
async def chat_history(
    container_id: Optional[int] = None,
    limit: int = 50,
    current_user: Client = Depends(get_current_client),
):
    """Get chat history."""
    params = {"client_id": current_user.id, "limit": limit}
    if container_id:
        params["container_id"] = container_id

    headers = {
        "Content-Type": "application/json",
        "x-api-key": SERVER_B_KEY,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{SERVER_B_URL}/api/chat/history",
            params=params,
            headers=headers,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()
