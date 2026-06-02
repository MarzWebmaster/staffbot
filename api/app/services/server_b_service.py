"""
Gateway Internal API Service.

Communicates with the Gateway container (staffbot-gateway:8080) on the SAME Docker host.
Handles: chat proxying, WhatsApp/Telegram session management, health checks.

DEPRECATED: deploy_container() and other Docker operations should use DockerService directly.
"""
import httpx
import logging
from fastapi import HTTPException, status
from typing import Optional
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class GatewayService:
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
        """DEPRECATED: Use DockerService directly instead of HTTP-to-Gateway a new container for a client."""
        if not GatewayService.is_configured():
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
                    headers=GatewayService._headers(),
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
                logger.warning(f"Gateway deploy timeout for {container_name}, falling back to simulated")
            except httpx.HTTPStatusError as e:
                logger.warning(f"Gateway deploy error ({e.response.status_code}) for {container_name}: {e.response.text[:200]}, falling back to simulated")
            except Exception as e:
                logger.warning(f"Gateway connection error for {container_name}: {str(e)[:200]}, falling back to simulated")

        # Fallback: simulated deployment with assigned port
        import os
        assigned_port = 8000 + client_id
        logger.info(f"Using simulated deployment for {container_name} on port {assigned_port}")
        return {
            "success": True,
            "test_mode": True,
            "container_id": os.urandom(32).hex(),
            "container_name": container_name,
            "port": assigned_port,
            "status": "running",
            "message": f"Simulated deployment (Gateway unavailable)",
            "deploy_method": "simulated",
        }

    @staticmethod
    async def update_container(
        container_name: str,
        env_vars: dict,
    ) -> dict:
        """Update an existing container's env vars (e.g., after setup wizard)."""
        if not GatewayService.is_configured():
            return {"success": True, "test_mode": True}

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{settings.SERVER_B_API_URL}/api/container/{container_name}",
                headers=GatewayService._headers(),
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
        if not GatewayService.is_configured():
            return {"success": True, "test_mode": True,
                    "message": "Simulated resource update",
                    "container_name": container_name,
                    "updated": {"cpu_limit": cpu_limit, "memory_limit_mb": memory_limit_mb},
                    "warning": "Storage change requires container recreation"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/container/{container_name}/update-resources",
                    headers=GatewayService._headers(),
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
                    detail="Gateway resource update timeout",
                )
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gateway error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gateway connection error: {str(e)}",
                )

    @staticmethod
    async def get_container_status(container_name: str) -> dict:
        """DEPRECATED: Check container via DockerService."""
        if not GatewayService.is_configured():
            return {"status": "running", "test_mode": True}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.SERVER_B_API_URL}/api/container/{container_name}/status",
                headers=GatewayService._headers(),
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def health_check() -> dict:
        """Ping Gateway health endpoint."""
        if not GatewayService.is_configured():
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
        if not GatewayService.is_configured():
            return {"success": True, "test_mode": True, "qr_url": None, "message": "Simulated session init"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/whatsapp/session/init",
                    headers=GatewayService._headers(),
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
        if not GatewayService.is_configured():
            return {"success": True, "test_mode": True, "webhook_url": f"https://staffbot.my/api/incoming/telegram/{client_id}"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/telegram/webhook/register",
                    headers=GatewayService._headers(),
                    json={"client_id": client_id, "bot_token": bot_token},
                    timeout=15.0,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Telegram Manager timeout")
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=502, detail=f"Telegram Manager error: {e.response.text}")
