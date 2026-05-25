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
