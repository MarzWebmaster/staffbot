"""Core StaffBot tools for customer Hermes agents (docs/TARGET_ARCHITECTURE.md §6).

Called by the StaffBot Hermes plugin inside the customer container with the
customer's proxy token (Authorization: Bearer sbk_...). The customer is taken
from the token, never from the request body.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.llm_proxy.tokens import parse_token
from app.models.client import Client
from app.models.task import Task
from app.services import agent_tools

router = APIRouter()


async def get_agent_client(authorization: Optional[str] = Header(None), db: AsyncSession = Depends(get_db)) -> Client:
    parsed = parse_token((authorization or "").removeprefix("Bearer ").strip())
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid StaffBot token")
    client = (await db.execute(select(Client).where(Client.id == parsed[0]))).scalar_one_or_none()
    if not client or (client.llm_token_version or 1) != parsed[1]:
        raise HTTPException(status_code=401, detail="Token revoked")
    if client.status != "active":
        raise HTTPException(status_code=403, detail=f"Account is {client.status}")
    return client


def _raise(e: agent_tools.ToolError):
    raise HTTPException(status_code=e.status, detail=e.message)


class TaskIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    assigned_to: Optional[str] = Field(None, max_length=100)
    agent: Optional[str] = Field(None, max_length=100)


class TaskPatch(BaseModel):
    status: Optional[Literal["pending", "in_progress", "completed", "cancelled"]] = None
    priority: Optional[Literal["low", "normal", "high", "urgent"]] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = Field(None, max_length=100)


def _task(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "description": t.description, "priority": t.priority,
            "status": t.status, "assigned_to": t.assigned_to,
            "created_at": t.created_at.isoformat() if t.created_at else None}


@router.post("/tasks", status_code=201)
async def create_task(data: TaskIn, client: Client = Depends(get_agent_client), db: AsyncSession = Depends(get_db)):
    t = Task(client_id=client.id, title=data.title, description=data.description, priority=data.priority,
             assigned_to=data.assigned_to, created_by_agent=data.agent or "hermes")
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _task(t)


@router.get("/tasks")
async def list_tasks(status: Optional[str] = None, limit: int = 50,
                     client: Client = Depends(get_agent_client), db: AsyncSession = Depends(get_db)):
    q = select(Task).where(Task.client_id == client.id)
    if status:
        q = q.where(Task.status == status)
    rows = (await db.execute(q.order_by(Task.created_at.desc()).limit(min(max(limit, 1), 200)))).scalars().all()
    return [_task(t) for t in rows]


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, data: TaskPatch, client: Client = Depends(get_agent_client),
                      db: AsyncSession = Depends(get_db)):
    t = (await db.execute(select(Task).where(Task.id == task_id, Task.client_id == client.id))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(t, k, v)
    await db.commit()
    await db.refresh(t)
    return _task(t)


@router.get("/webhooks")
async def list_webhooks(client: Client = Depends(get_agent_client), db: AsyncSession = Depends(get_db)):
    return await agent_tools.list_webhooks(db, client.id)


class WebhookCall(BaseModel):
    endpoint_name: str
    path: str = ""
    method: str = "GET"
    body: Optional[dict] = None
    query_params: Optional[dict] = None


@router.post("/webhook")
async def call_webhook(data: WebhookCall, client: Client = Depends(get_agent_client), db: AsyncSession = Depends(get_db)):
    try:
        return await agent_tools.call_webhook(db, client.id, data.endpoint_name, data.path, data.method,
                                              data.body, data.query_params)
    except agent_tools.ToolError as e:
        _raise(e)


class EmailIn(BaseModel):
    to: str
    subject: str
    body: str
    cc: Optional[str] = None


@router.post("/email")
async def send_email(data: EmailIn, client: Client = Depends(get_agent_client), db: AsyncSession = Depends(get_db)):
    try:
        return await agent_tools.send_email(db, client.id, data.to, data.subject, data.body, data.cc)
    except agent_tools.ToolError as e:
        _raise(e)
