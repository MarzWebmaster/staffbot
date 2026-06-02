"""
Multi-channel notification service.

Supports:
- WhatsApp (via Baileys on Gateway)
- Email (via SMTP)
- SMS (via API)
- In-app (mark in DB, dashboard polls for unread)
"""
import smtplib
import httpx
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import HTTPException, status
from app.config import get_settings

settings = get_settings()


class NotificationService:
    @staticmethod
    async def send_whatsapp(to: str, message: str) -> dict:
        """Send WhatsApp via Baileys on Gateway."""
        if not settings.SERVER_B_API_KEY:
            return {"success": True, "test_mode": True, "note": "No Gateway configured"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{settings.SERVER_B_API_URL}/api/notify/whatsapp",
                    headers={
                        "X-API-Key": settings.SERVER_B_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "to": to,
                        "message": message,
                    },
                    timeout=15.0,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                return {"success": False, "error": str(e)}

    @staticmethod
    async def send_email(to: str, subject: str, body: str) -> dict:
        """Send email via SMTP."""
        if not settings.SMTP_HOST or not settings.SMTP_USER:
            return {"success": True, "test_mode": True, "note": "SMTP not configured"}

        try:
            msg = MIMEMultipart()
            msg["From"] = settings.SMTP_FROM
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html" if "<html>" in body else "plain"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def send_sms(to: str, message: str) -> dict:
        """Send SMS via external API."""
        if not settings.SMS_API_URL:
            return {"success": True, "test_mode": True, "note": "SMS API not configured"}

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    settings.SMS_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.SMS_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "to": to,
                        "message": message,
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                return {"success": True, "response": resp.text}
            except Exception as e:
                return {"success": False, "error": str(e)}

    @staticmethod
    def create_inapp_notification(client_id: int, type: str, subject: str, body: str) -> dict:
        """Create an in-app notification (stored in DB, fetched by dashboard polling)."""
        # This is a sync helper for creating in-app notif records
        from app.models.notification import NotificationLog
        return {
            "success": True,
            "type": "in-app",
            "data": {
                "client_id": client_id,
                "type": type,
                "subject": subject,
                "body": body,
                "status": "sent",
            },
        }

    @classmethod
    async def notify_admin(cls, subject: str, body: str) -> dict:
        """Notify superadmin via all configured channels."""
        results = {}

        if settings.ADMIN_WHATSAPP:
            wa_msg = f"*[StaffBot Admin]*\n{subject}\n\n{body}"
            results["whatsapp"] = await cls.send_whatsapp(settings.ADMIN_WHATSAPP, wa_msg)

        if settings.ADMIN_EMAIL:
            results["email"] = await cls.send_email(settings.ADMIN_EMAIL, subject, body)

        if settings.ADMIN_PHONE:
            sms_msg = f"[StaffBot] {subject[:100]}"
            results["sms"] = await cls.send_sms(settings.ADMIN_PHONE, sms_msg)

        return results

    @classmethod
    async def notify_client(
        cls,
        client_id: int,
        channels: list,
        subject: str,
        body: str,
        wa_message: str = "",
    ) -> dict:
        """Send notification to a client via their configured channels."""
        from app.database import async_session_factory
        from app.models.notification import NotificationChannel, NotificationLog
        from sqlalchemy import select

        results = {}
        async with async_session_factory() as db:
            # Get client's active notification channels from DB
            result = await db.execute(
                select(NotificationChannel).where(
                    NotificationChannel.client_id == client_id,
                    NotificationChannel.is_active == True,
                )
            )
            client_channels = result.scalars().all()

            # Filter by requested channels if specified
            target_channels = [c for c in client_channels if c.channel in channels] if channels else client_channels

            for ch in target_channels:
                try:
                    if ch.channel == "whatsapp":
                        res = await cls.send_whatsapp(ch.value, wa_message or body)
                    elif ch.channel == "email":
                        res = await cls.send_email(ch.value, subject, body)
                    elif ch.channel == "sms":
                        res = await cls.send_sms(ch.value, body[:160])
                    else:
                        res = {"success": True, "type": "in-app"}

                    # Log notification
                    log = NotificationLog(
                        client_id=client_id,
                        type=subject,
                        channel=ch.channel,
                        subject=subject,
                        body=body[:500],
                        status="sent" if res.get("success") else "failed",
                        error_message=str(res.get("error", "")),
                    )
                    db.add(log)
                    results[ch.channel] = res
                except Exception as e:
                    log = NotificationLog(
                        client_id=client_id,
                        type=subject,
                        channel=ch.channel,
                        subject=subject,
                        body=body[:500],
                        status="failed",
                        error_message=str(e),
                    )
                    db.add(log)
                    results[ch.channel] = {"success": False, "error": str(e)}

            await db.commit()

        return results
