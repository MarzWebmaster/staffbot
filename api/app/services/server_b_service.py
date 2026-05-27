"""
Server B Internal API Service.

Handles communication between Server A (Public) and Server B (Private/Containers)
via WireGuard VPN tunnel (10.0.0.0/24 subnet).
"""
import httpx
from fastapi import HTTPException, status
from typing import Optional
from app.config import get_settings

settings = get_settings()


class ServerBService:
    @staticmethod
    def is_configured() -> bool:
        return bool(settings.SERVER_B_API_KEY)

    @staticmethod
    def _headers() -> dict:
        return {
            "X-API-Key": settings.SERVER_B_API_KEY,
            "Content-Type": "application/json",
        }

    @staticmethod
    async def deploy_container(
        client_id: int,
        container_name: str,
        subdomain: str,
        env_vars: dict,
        skills: Optional[list] = None,
        cpu_limit: float = 1.0,
        memory_limit_mb: int = 512,
        storage_limit_gb: int = 10,
    ) -> dict:
        """Request Server B to deploy a new container for a client."""
        if not ServerBService.is_configured():
            return {
                "success": True,
                "test_mode": True,
                "container_id": f"container_{client_id}",
                "port": 8000 + client_id,
                "message": "Simulated deployment",
            }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/deploy",
                    headers=ServerBService._headers(),
                    json={
                        "client_id": client_id,
                        "container_name": container_name,
                        "subdomain": subdomain,
                        "env_vars": env_vars,
                        "skills": skills or [],
                        "cpu_limit": cpu_limit,
                        "memory_limit_mb": memory_limit_mb,
                        "storage_limit_gb": storage_limit_gb,
                    },
                    timeout=120.0,  # 2 min timeout for deployment
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Server B deployment timeout (2 min)",
                )
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Server B error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Server B connection error: {str(e)}",
                )

    @staticmethod
    async def update_container(
        container_name: str,
        env_vars: dict,
    ) -> dict:
        """Update an existing container's env vars (e.g., after setup wizard)."""
        if not ServerBService.is_configured():
            return {"success": True, "test_mode": True}

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{settings.SERVER_B_API_URL}/api/container/{container_name}",
                headers=ServerBService._headers(),
                json={"env_vars": env_vars},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def update_resource_limits(
        container_name: str,
        cpu_limit: float = 1.0,
        memory_limit_mb: int = 512,
        storage_limit_gb: int = 10,
    ) -> dict:
        """Update an existing container's resource limits (CPU/RAM) without restart.

        NOTE: Storage limit changes require container recreation.
        """
        if not ServerBService.is_configured():
            return {"success": True, "test_mode": True,
                    "message": "Simulated resource update",
                    "container_name": container_name,
                    "updated": {"cpu_limit": cpu_limit, "memory_limit_mb": memory_limit_mb},
                    "warning": "Storage change requires container recreation"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/container/{container_name}/update-resources",
                    headers=ServerBService._headers(),
                    json={
                        "cpu_limit": cpu_limit,
                        "memory_limit_mb": memory_limit_mb,
                        "storage_limit_gb": storage_limit_gb,
                    },
                    timeout=15.0,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Server B resource update timeout",
                )
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Server B error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Server B connection error: {str(e)}",
                )

    @staticmethod
    async def get_container_status(container_name: str) -> dict:
        """Check container status on Server B."""
        if not ServerBService.is_configured():
            return {"status": "running", "test_mode": True}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.SERVER_B_API_URL}/api/container/{container_name}/status",
                headers=ServerBService._headers(),
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def health_check() -> dict:
        """Ping Server B API Gateway."""
        if not ServerBService.is_configured():
            return {"status": "ok", "test_mode": True}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{settings.SERVER_B_API_URL}/health",
                    timeout=5.0,
                )
                return resp.json()
            except Exception:
                return {"status": "unreachable"}

    @staticmethod
    async def whatsapp_init_session(
        client_id: int,
        auth_path: str,
    ) -> dict:
        """Request Baileys Manager to initialize a WhatsApp session for a client.
        Returns QR code data for the client to scan.
        """
        if not ServerBService.is_configured():
            return {"success": True, "test_mode": True, "qr_url": None, "message": "Simulated session init"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/whatsapp/session/init",
                    headers=ServerBService._headers(),
                    json={"client_id": client_id, "auth_path": auth_path},
                    timeout=30.0,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Baileys Manager timeout")
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=502, detail=f"Baileys Manager error: {e.response.text}")

    @staticmethod
    async def telegram_register_webhook(
        client_id: int,
        bot_token: str,
    ) -> dict:
        """Register a Telegram webhook so messages route to this client's container."""
        if not ServerBService.is_configured():
            return {"success": True, "test_mode": True, "webhook_url": f"https://staffbot.my/api/incoming/telegram/{client_id}"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/telegram/webhook/register",
                    headers=ServerBService._headers(),
                    json={"client_id": client_id, "bot_token": bot_token},
                    timeout=15.0,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Telegram Manager timeout")
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=502, detail=f"Telegram Manager error: {e.response.text}")
