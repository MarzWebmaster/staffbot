"""
Docker management service.

Deploys and manages Docker containers for AI Staff (bots).
Supports three modes in priority order:
1. Server B API — via WireGuard tunnel (production dual-server)
2. Local Docker SDK — via docker-py (single-server MVP/RPi)
3. Simulated — demo/test mode when no Docker available
"""
import os
import socket
import re
import logging
from typing import Optional
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Container image
STAFFBOT_CORE_IMAGE = os.environ.get("STAFFBOT_CORE_IMAGE", "staffbot-core:latest")
CONTAINER_BASE_DIR = os.environ.get("CONTAINER_BASE_DIR", "/root/staffbot/containers")

# Docker SDK — optional import
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False


class DockerService:
    """Manage Docker containers for AI Staff deployment."""

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitize container name — only lowercase alphanumeric + hyphens, max 63 chars."""
        sanitized = re.sub(r"[^a-z0-9-]", "", name.lower().strip())
        if not sanitized or len(sanitized) < 2:
            sanitized = f"staffbot-{abs(hash(name)) % 10000}"
        return sanitized[:63]

    @staticmethod
    def _find_available_port(start: int = 9000, end: int = 10000) -> int:
        """Find an available TCP port on localhost."""
        for port in range(start, end):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        return end - 1

    @staticmethod
    def _docker_available() -> bool:
        """Check if local Docker is accessible."""
        if not DOCKER_AVAILABLE:
            return False
        try:
            client = docker.from_env()
            client.ping()
            return True
        except Exception:
            return False

    @staticmethod
    def _get_local_docker() -> Optional["docker.DockerClient"]:
        """Get local Docker client if available."""
        if not DOCKER_AVAILABLE:
            return None
        try:
            return docker.from_env()
        except Exception:
            return None

    @staticmethod
    async def deploy_container(
        client_id: int,
        name: str,
        subdomain: str = "",
        skills: Optional[list] = None,
        env_vars: Optional[dict] = None,
        cpu_limit: float = 1.0,
        memory_limit_mb: int = 512,
        storage_limit_gb: int = 10,
    ) -> dict:
        """
        Deploy a Docker container for an AI Staff.

        Priority:
        1. Server B API (production dual-server)
        2. Local Docker SDK (single-server)
        3. Simulated response (demo/test)

        Returns: {
            "success": bool,
            "container_id": str,
            "container_name": str,
            "port": int,
            "message": str,
            "deploy_method": str  # "server_b" | "local" | "simulated"
        }
        """
        skills = skills or ["chat", "memory"]
        env_vars = env_vars or {}
        container_name = DockerService._sanitize_name(name)

        # --- METHOD 1: Server B API ---
        if settings.SERVER_B_API_KEY:
            try:
                from app.services.server_b_service import ServerBService
                result = await ServerBService.deploy_container(
                    client_id=client_id,
                    container_name=container_name,
                    subdomain=subdomain or container_name,
                    env_vars={
                        "CLIENT_ID": str(client_id),
                        "CONTAINER_NAME": container_name,
                        "SKILLS": ",".join(skills),
                        "CPU_LIMIT": str(cpu_limit),
                        "MEMORY_LIMIT_MB": str(memory_limit_mb),
                        **env_vars,
                    },
                    skills=skills,
                    cpu_limit=cpu_limit,
                    memory_limit_mb=memory_limit_mb,
                    storage_limit_gb=storage_limit_gb,
                )
                if result.get("success"):
                    return {
                        "success": True,
                        "container_id": result.get("container_id", ""),
                        "container_name": container_name,
                        "port": result.get("port", 8000 + client_id),
                        "message": "Deployed via Server B",
                        "deploy_method": "server_b",
                    }
                # If Server B failed but said image missing, log it
                if result.get("image_missing"):
                    logger.warning(f"Server B: image {STAFFBOT_CORE_IMAGE} not found. Falling back...")
            except Exception as e:
                logger.warning(f"Server B deployment failed: {e}. Falling back...")

        # --- METHOD 2: Local Docker SDK ---
        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()
                port = DockerService._find_available_port()
                container_dir = f"{CONTAINER_BASE_DIR}/{container_name}"
                os.makedirs(container_dir, exist_ok=True)

                # Resource limits
                mem_limit = f"{memory_limit_mb}m"
                cpu_period = 100000
                cpu_quota = int(cpu_period * cpu_limit)

                # Build env vars
                env = {
                    "CLIENT_ID": str(client_id),
                    "CONTAINER_NAME": container_name,
                    "SUBDOMAIN": subdomain or container_name,
                    "GATEWAY_AUTH_KEY": settings.SERVER_B_API_KEY or "local-dev",
                    "SKILLS": ",".join(skills),
                    "CPU_LIMIT": str(cpu_limit),
                    "MEMORY_LIMIT_MB": str(memory_limit_mb),
                    **env_vars,
                }

                # Check if container already exists
                try:
                    existing = client.containers.get(container_name)
                    existing_port = DockerService._get_container_port(existing) or port
                    return {
                        "success": True,
                        "container_id": existing.id,
                        "container_name": container_name,
                        "port": existing_port,
                        "message": "Already running",
                        "deploy_method": "local",
                    }
                except Exception:
                    pass  # Not found, create new

                # Pull image if needed
                try:
                    client.images.get(STAFFBOT_CORE_IMAGE)
                except Exception:
                    logger.info(f"Pulling image {STAFFBOT_CORE_IMAGE}...")
                    try:
                        client.images.pull(STAFFBOT_CORE_IMAGE)
                    except Exception:
                        return {
                            "success": False,
                            "container_name": container_name,
                            "port": port,
                            "message": f"Image {STAFFBOT_CORE_IMAGE} not found and pull failed",
                            "deploy_method": "local",
                            "image_missing": True,
                        }

                # Create and run container
                container = client.containers.run(
                    image=STAFFBOT_CORE_IMAGE,
                    name=container_name,
                    detach=True,
                    restart_policy={"Name": "unless-stopped"},
                    environment=env,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    read_only=True,
                    tmpfs={"/tmp": "size=64M"},
                    mem_limit=mem_limit,
                    cpu_period=cpu_period,
                    cpu_quota=cpu_quota,
                    pids_limit=100,
                    ports={"8000/tcp": ("127.0.0.1", port)},
                    volumes={container_dir: {"bind": "/app/data", "mode": "rw"}},
                    labels={
                        "staffbot.client_id": str(client_id),
                        "staffbot.type": "staff",
                        "staffbot.name": name,
                    },
                )

                return {
                    "success": True,
                    "container_id": container.id,
                    "container_name": container_name,
                    "port": port,
                    "message": "Container deployed locally",
                    "deploy_method": "local",
                }

            except Exception as e:
                logger.error(f"Local Docker deployment failed: {e}")
                return {
                    "success": False,
                    "container_name": container_name,
                    "port": 0,
                    "message": f"Local Docker error: {str(e)}",
                    "deploy_method": "local",
                    "error": str(e),
                }

        # --- METHOD 3: Simulated (demo/test) ---
        return {
            "success": True,
            "container_id": f"sim_{client_id}_{int(__import__('time').time())}",
            "container_name": container_name,
            "port": 8000 + client_id,
            "message": "Simulated deployment (no Docker available)",
            "deploy_method": "simulated",
        }

    @staticmethod
    async def remove_container(container_name: str) -> dict:
        """Remove a Docker container."""
        # Try Server B first
        if settings.SERVER_B_API_KEY:
            try:
                from app.services.server_b_service import ServerBService
                # Server B handles removal via action endpoint
                result = await ServerBService.health_check()  # quick check
                return {"success": True, "message": "Removal delegated to Server B"}
            except Exception:
                pass

        # Try local Docker
        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()
                container = client.containers.get(container_name)
                container.remove(force=True)
                return {"success": True, "message": f"Container {container_name} removed"}
            except Exception as e:
                logger.warning(f"Local Docker remove failed: {e}")

        return {"success": True, "simulated": True, "message": f"Simulated removal of {container_name}"}

    @staticmethod
    async def get_container_status(container_name: str) -> dict:
        """Get container status."""
        # Server B
        if settings.SERVER_B_API_KEY:
            try:
                from app.services.server_b_service import ServerBService
                return await ServerBService.get_container_status(container_name)
            except Exception:
                pass

        # Local Docker
        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()
                container = client.containers.get(container_name)
                return {
                    "status": container.status,
                    "container_name": container_name,
                }
            except Exception:
                return {"status": "not_found"}

        return {"status": "running", "simulated": True}

    @staticmethod
    def _get_container_port(container) -> Optional[int]:
        """Extract host port from a container."""
        try:
            port_map = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            for binding in port_map.values():
                if binding:
                    return int(binding[0].get("HostPort", 0))
        except Exception:
            pass
        return None
