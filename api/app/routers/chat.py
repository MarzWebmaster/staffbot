"""Chat router — proxies to Server B gateway."""
import os, httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from app.middleware.auth import get_current_client
from app.models.client import Client

router = APIRouter()

SERVER_B_URL = os.environ.get("STAFFBOT_SERVER_B_API_URL", "http://69.161.221.104:8080")
SERVER_B_KEY = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")

HEADERS = {"Content-Type": "application/json", "x-api-key": SERVER_B_KEY}

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
):
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
            },
            headers=HEADERS,
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
    params = {"client_id": current_user.id, "limit": limit}
    if container_id:
        params["container_id"] = container_id
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{SERVER_B_URL}/api/chat/history",
            params=params,
            headers=HEADERS,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()
