"""
Deployment orchestration service.

Coordinates the full deployment flow when a new client subscribes:
1. Generate unique subdomain
2. Create DNS record via Cloudflare
3. Request container deployment on Server B
4. Setup reverse proxy on Server B
5. Update database state
6. Send notifications to client + admin
"""
import re
import secrets
from typing import Optional
from app.services.cloudflare_service import CloudflareService
from app.services.server_b_service import ServerBService
from app.services.notification_service import NotificationService
from app.config import get_settings

settings = get_settings()


class DeploymentService:
    @staticmethod
    def generate_subdomain(company_name: str = "", client_id: int = 0) -> str:
        """Generate a unique subdomain based on company name."""
        if company_name:
            # Slugify: lowercase, remove special chars, replace spaces with hyphens
            base = re.sub(r"[^a-z0-9-]", "", company_name.lower().replace(" ", "-"))
            base = base[:30]  # Max 30 chars
            if base:
                suffix = secrets.token_hex(3)  # 6-char random suffix
                return f"{base}-{suffix}"

        # Fallback: random alphanumeric
        return f"client-{secrets.token_hex(4)}"

    @staticmethod
    async def deploy(client_data: dict) -> dict:
        """Full deployment pipeline."""
        client_id = client_data["id"]
        company = client_data.get("company", "")
        subdomain = DeploymentService.generate_subdomain(company, client_id)

        # 1. Create DNS record
        dns_result = await CloudflareService.create_dns_record(
            subdomain=subdomain,
            ip_address=settings.DOMAIN,  # Server A IP resolves via staffbot.my
            proxy=False,
        )

        # 2. Prepare env vars for container
        env_vars = {
            "CLIENT_ID": str(client_id),
            "CLIENT_NAME": client_data.get("name", ""),
            "CLIENT_EMAIL": client_data.get("email", ""),
            "COMPANY": company or "",
            "SUBDOMAIN": f"{subdomain}.{settings.DOMAIN}",
            "DATABASE_URL": settings.DATABASE_URL,
            "WHATSAPP_AUTH_PATH": f"/root/staffbot/auth/whatsapp/{client_id}",
        }

        # Add telegram token if provided (decrypted)
        telegram_encrypted = client_data.get("telegram_token_encrypted")
        if telegram_encrypted:
            from app.utils.encryption import decrypt_value
            try:
                env_vars["TELEGRAM_TOKEN"] = decrypt_value(telegram_encrypted)
            except Exception:
                pass  # Not critical, silently skip

        # Fetch resource limits from package
        cpu_limit = float(client_data.get("cpu_limit", 1.0))
        memory_limit_mb = int(client_data.get("memory_limit_mb", 512))
        storage_limit_gb = int(client_data.get("storage_limit_gb", 10))

        # Add resource limits to env vars for container awareness
        env_vars["CPU_LIMIT"] = str(cpu_limit)
        env_vars["MEMORY_LIMIT_MB"] = str(memory_limit_mb)
        env_vars["STORAGE_LIMIT_GB"] = str(storage_limit_gb)

        # 3. Request container deployment on Server B
        container_result = await ServerBService.deploy_container(
            client_id=client_id,
            container_name=f"staffbot-{subdomain}",
            subdomain=subdomain,
            env_vars=env_vars,
            skills=["chat", "memory", "tasks"],
            cpu_limit=cpu_limit,
            memory_limit_mb=memory_limit_mb,
            storage_limit_gb=storage_limit_gb,
        )

        container_port = container_result.get("port", 8000 + client_id)
        container_id = container_result.get("container_id", f"container_{client_id}")

        # 4. Initialize Hybrid Brain memory bank for this client
        try:
            await ServerBService.hybrid_brain_init(client_id=client_id)
        except Exception:
            pass  # Non-critical — will init on first use

        return {
            "subdomain": f"{subdomain}.{settings.DOMAIN}",
            "subdomain_raw": subdomain,
            "port": container_port,
            "container_id": container_id,
            "dns": dns_result,
            "container": container_result,
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
        # Client notification
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

        # Admin notification
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
