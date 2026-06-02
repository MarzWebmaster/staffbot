"""
Deployment orchestration service.

Coordinates the full deployment flow when a new client subscribes:
1. Generate unique subdomain
2. Create DNS record via Cloudflare
3. Deploy container directly on this server via DockerService
4. Update database state
5. Send notifications to client + admin

ALL services run on ONE server (Tencent). No external Gateway.
"""
import re
import secrets
import asyncio
from typing import Optional
import httpx
from app.services.cloudflare_service import CloudflareService
from app.services.docker_service import DockerService
from app.services.server_b_service import GatewayService
from app.services.notification_service import NotificationService
from app.config import get_settings

settings = get_settings()

logger = __import__('logging').getLogger(__name__)


class DeploymentService:
    @staticmethod
    def generate_subdomain(company_name: str = "", client_id: int = 0) -> str:
        """Generate a unique subdomain based on company name."""
        if company_name:
            base = re.sub(r"[^a-z0-9-]", "", company_name.lower().replace(" ", "-"))
            base = base[:30]
            if base:
                suffix = secrets.token_hex(3)
                return f"{base}-{suffix}"

        return f"client-{secrets.token_hex(4)}"

    @staticmethod
    async def deploy(client_data: dict) -> dict:
        """Full deployment pipeline — deploys container directly on this server."""
        client_id = client_data["id"]
        company = client_data.get("company", "")
        client_name = client_data.get("name", "")

        # Use pre-reserved subdomain if available, otherwise auto-generate
        subdomain = client_data.get("subdomain")
        if not subdomain:
            subdomain = DeploymentService.generate_subdomain(company, client_id)

        # 1. Create DNS record
        dns_result = await CloudflareService.create_dns_record(
            subdomain=subdomain,
            ip_address=settings.DOMAIN,
            proxy=False,
        )

        # Fetch resource limits from package
        cpu_limit = float(client_data.get("cpu_limit", 1.0))
        memory_limit_mb = int(client_data.get("memory_limit_mb", 512))
        storage_limit_gb = int(client_data.get("storage_limit_gb", 10))
        package = client_data.get("package", "basic")

        # 2. Deploy container DIRECTLY via DockerService (same server — no HTTP hop)
        container_result = DockerService.deploy_client_container(
            client_id=client_id,
            client_name=client_name,
            subdomain=subdomain,
            package=package,
            cpu_limit=cpu_limit,
            memory_limit_mb=memory_limit_mb,
            storage_limit_gb=storage_limit_gb,
        )

        container_port = container_result.get("port", 8000 + client_id)
        container_id = container_result.get("container_id", f"container_{client_id}")
        container_name = container_result.get("container_name", f"staffbot-{subdomain}")

        return {
            "subdomain": f"{subdomain}.{settings.DOMAIN}",
            "subdomain_raw": subdomain,
            "port": container_port,
            "container_id": container_id,
            "container_name": container_name,
            "dns": dns_result,
            "container": container_result,
        }

    @staticmethod
    async def verify_deployment(subdomain_raw: str, port: int, container_id: str, warmup_delay: int = 15) -> dict:
        """
        Post-deployment verification: check container, port, and subdomain are actually live.

        Args:
            warmup_delay: seconds to wait before checking (containers need time to start)
        """
        checks = {}
        errors = []

        # ── Wait for container warmup ─────────────────────────────
        logger.info(f"Waiting {warmup_delay}s for container warmup before verifying {subdomain_raw}...")
        await asyncio.sleep(warmup_delay)

        full_subdomain = f"{subdomain_raw}.{settings.DOMAIN}"

        # ── Check 1: DNS resolution ──────────────────────────────
        try:
            import socket
            socket.gethostbyname(full_subdomain)
            checks["dns"] = True
        except Exception as e:
            checks["dns"] = False
            errors.append(f"DNS: {full_subdomain} not resolving — {str(e)[:80]}")

        # ── Check 2: Port accessible on this server ──────────────
        if port is not None and port > 0:
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()
                checks["port"] = (result == 0)
                if result != 0:
                    errors.append(f"Port: {port} not listening")
            except Exception as e:
                checks["port"] = False
                errors.append(f"Port check failed: {str(e)[:80]}")
        else:
            checks["port"] = "skipped"
            logger.info(f"Skipping port check — port is None (simulated deployment)")

        # ── Check 3: HTTP response from subdomain ────────────────
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                resp = await client.get(f"https://{full_subdomain}/", follow_redirects=True)
                checks["http"] = resp.status_code in (200, 302, 301, 307, 308)
                checks["http_status"] = resp.status_code
                if not checks["http"]:
                    errors.append(f"HTTP: {full_subdomain} returned {resp.status_code}")
        except Exception as e:
            checks["http"] = False
            checks["http_status"] = None
            errors.append(f"HTTP: {full_subdomain} unreachable — {str(e)[:80]}")

        # ── Check 4: Container health via Gateway ─────────────────
        try:
            health = await GatewayService.health_check()
            checks["container"] = health.get("status") == "ok"
            if not checks["container"]:
                errors.append(f"Gateway: health check failed — {health}")
        except Exception as e:
            checks["container"] = False
            errors.append(f"Gateway: health check error — {str(e)[:80]}")

        ok = len(errors) == 0
        summary = "✅ All checks passed" if ok else f"⚠️ {len(errors)}/{len(checks)} checks failed"

        logger.info(f"Deployment verification for {full_subdomain}: {summary}")
        if errors:
            logger.warning(f"Verification errors: {'; '.join(errors)}")

        return {
            "ok": ok,
            "summary": summary,
            "checks": checks,
            "errors": errors,
        }

    @staticmethod
    async def send_deployment_notifications(
        client_id: int,
        client_name: str,
        client_email: str,
        subdomain: str,
        package: str,
        amount: float,
    ) -> dict:
        """Send post-deployment notifications to client and admin."""
        wa_message = (
            f"✅ *StaffBot.my — Your AI Staff is Ready!*\n\n"
            f"Hai {client_name}!\n\n"
            f"Your StaffBot has been deployed successfully. Here are your access details:\n\n"
            f"🌐 *Dashboard:* https://{subdomain}/dashboard\n"
            f"📧 *Email:* {client_email}\n"
            f"📦 *Package:* {package.title()}\n\n"
            f"Next steps:\n"
            f"1. Login to your dashboard\n"
            f"2. Connect your Telegram bot\n"
            f"3. Add your company knowledge\n\n"
            f"Need help? Just reply to this message! 🚀"
        )

        email_body = f"""
        <html><body>
        <h2>✅ Your StaffBot is Ready!</h2>
        <p>Hi <strong>{client_name}</strong>,</p>
        <p>Your StaffBot has been deployed successfully!</p>
        <table border="1" cellpadding="8" cellspacing="0">
            <tr><td><strong>Dashboard</strong></td><td><a href="https://{subdomain}/dashboard">https://{subdomain}/dashboard</a></td></tr>
            <tr><td><strong>Email</strong></td><td>{client_email}</td></tr>
            <tr><td><strong>Package</strong></td><td>{package.title()}</td></tr>
        </table>
        </body></html>
        """

        client_result = await NotificationService.notify_client(
            client_id=client_id,
            channels=["whatsapp", "email", "in-app"],
            subject="StaffBot.my — Deployment Complete ✅",
            body=email_body,
            wa_message=wa_message,
        )

        admin_body = (
            f"New Payment & Deployment:\n"
            f"• Name: {client_name}\n"
            f"• Email: {client_email}\n"
            f"• Package: {package.title()}\n"
            f"• Amount: RM{amount:.2f}\n"
            f"• Subdomain: {subdomain}"
        )

        admin_result = await NotificationService.notify_admin(
            subject="💰 New Payment Received + Deployment Complete",
            body=admin_body,
        )

        return {
            "client_notifications": client_result,
            "admin_notifications": admin_result,
        }
