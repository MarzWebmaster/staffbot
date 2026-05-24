"""StaffBot Core Agent — runs inside each client container."""
import os, httpx, asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="StaffBot Core Agent")

CLIENT_ID = os.environ.get("CLIENT_ID", "0")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://staffbot-gateway:8080")
AUTH_KEY = os.environ.get("GATEWAY_AUTH_KEY", "")
HEADERS = {"x-api-key": AUTH_KEY, "Content-Type": "application/json"}

@app.get("/health")
async def health():
    return {"status": "ok", "client_id": CLIENT_ID}

@app.post("/chat")
async def chat(content: str, provider: str = "openrouter", api_key: Optional[str] = None):
    """Proxy chat to gateway LLM."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{GATEWAY_URL}/api/chat/send",
            json={"client_id": int(CLIENT_ID), "content": content, "provider": provider, "api_key": api_key},
            headers=HEADERS,
        )
    return resp.json()

@app.get("/memory/recent")
async def recent_memory(limit: int = 10):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GATEWAY_URL}/api/chat/history?client_id={CLIENT_ID}&limit={limit}",
            headers=HEADERS,
        )
    return resp.json()
