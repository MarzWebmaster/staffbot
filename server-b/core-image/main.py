#!/usr/bin/env python3
"""StaffBot.my — Client Container Core
Each client gets one of these containers.
Config via env vars: CLIENT_ID, GATEWAY_AUTH_KEY, SUBDOMAIN, SKILLS, etc.
Container ONLY talks through gateway — NO direct DB access.
"""
import os, httpx
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

CLIENT_ID = os.environ.get("CLIENT_ID", "0")
SUBDOMAIN = os.environ.get("SUBDOMAIN", "")
SKILLS = os.environ.get("SKILLS", "chat,memory").split(",")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://staffbot-gateway:8080")
GATEWAY_AUTH_KEY = os.environ.get("GATEWAY_AUTH_KEY", "")

app = FastAPI(title=f"StaffBot Core - Client {CLIENT_ID}", version="1.0.0")


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok", "client_id": CLIENT_ID, "skills": SKILLS}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Basic chat endpoint. For MVP, returns a placeholder."""
    return ChatResponse(
        reply=f"StaffBot Client {CLIENT_ID} sedia. Fungsi chat penuh akan tersedia tidak lama lagi.",
        session_id=req.session_id,
    )


@app.post("/memory/save")
async def save_memory(content: str, metadata: dict = {}):
    """Save to memory DB via gateway — NO direct DB access."""
    if not GATEWAY_AUTH_KEY:
        return {"success": False, "error": "Gateway auth key not configured"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GATEWAY_URL}/api/memory/save",
            json={"client_id": int(CLIENT_ID), "content": content, "metadata": metadata},
            headers={"X-API-Key": GATEWAY_AUTH_KEY},
            timeout=10.0,
        )
        return resp.json()


@app.post("/memory/search")
async def search_memory(query: str, limit: int = 5):
    """Search memory via gateway — NO direct DB access."""
    if not GATEWAY_AUTH_KEY:
        return {"success": False, "error": "Gateway auth key not configured"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GATEWAY_URL}/api/memory/search",
            json={"client_id": int(CLIENT_ID), "query": query, "limit": limit},
            headers={"X-API-Key": GATEWAY_AUTH_KEY},
            timeout=10.0,
        )
        return resp.json()
