"""Tasks router — proxies to Server B gateway."""
import os, httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from app.middleware.auth import get_current_client
from app.models.client import Client

router = APIRouter()
SERVER_B_URL = os.environ.get("STAFFBOT_SERVER_B_API_URL", "http://69.161.221.104:8080")
SERVER_B_KEY = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")
HEADERS = {"Content-Type": "application/json", "x-api-key": SERVER_B_KEY}

class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    priority: str = "normal"
    assigned_to: Optional[str] = None

class TaskUpdateRequest(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None

@router.post("/create")
async def create_task(
    data: TaskCreateRequest,
    current_user: Client = Depends(get_current_client),
):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SERVER_B_URL}/api/tasks/create",
            json={
                "client_id": current_user.id,
                "title": data.title,
                "description": data.description,
                "priority": data.priority,
                "assigned_to": data.assigned_to,
            },
            headers=HEADERS,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()

@router.get("/list")
async def list_tasks(
    status: Optional[str] = None,
    current_user: Client = Depends(get_current_client),
):
    params = {"client_id": current_user.id}
    if status:
        params["status"] = status
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{SERVER_B_URL}/api/tasks/list",
            params=params,
            headers=HEADERS,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()

@router.put("/{task_id}")
async def update_task(
    task_id: int,
    data: TaskUpdateRequest,
    current_user: Client = Depends(get_current_client),
):
    payload = {}
    if data.status: payload["status"] = data.status
    if data.description is not None: payload["description"] = data.description
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(
            f"{SERVER_B_URL}/api/tasks/{task_id}",
            json=payload,
            headers=HEADERS,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()
