"""
Webhooks router.

Handles incoming webhooks from:
- Stripe (payment events)
- Gateway (container status updates)
"""
from fastapi import APIRouter, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from datetime import datetime, timezone
from typing import Optional

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.services.stripe_service import StripeService
from app.services.deployment_service import DeploymentService
from app.services.notification_service import NotificationService
from app.config import get_settings

router = APIRouter()
settings = get_settings()

import logging
logger = logging.getLogger(__name__)


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Stripe webhook events.

    Primary event: checkout.session.completed
    Triggers: full deployment pipeline
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    await StripeService.configure_from_db(db)
    event = await StripeService.verify_webhook(payload, sig_header)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        customer_email = metadata.get("customer_email", session.get("customer_email", ""))
        customer_name = metadata.get("customer_name", "")
        package = metadata.get("package", "basic")
        amount = session.get("amount_total", 0) / 100.0  # Convert cents to MYR

        # Find or create client
        from sqlalchemy import select
        result = await db.execute(select(Client).where(Client.email == customer_email))
        client = result.scalar_one_or_none()

        if not client:
            # Auto-register if doesn't exist
            from app.models.client import Client as ClientModel
            client = ClientModel(
                name=customer_name or customer_email.split("@")[0],
                email=customer_email,
                package=package,
                status="pending",
            )
            db.add(client)
            await db.flush()

            sub = Subscription(
                client_id=client.id,
                stripe_session_id=session["id"],
                package=package,
                status="active",
                start_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(sub)
        else:
            # Update existing subscription
            client.package = package
            sub_result = await db.execute(
                select(Subscription).where(Subscription.client_id == client.id)
            )
            sub = sub_result.scalar_one_or_none()
            if sub:
                sub.package = package
                sub.status = "active"
                sub.stripe_session_id = session["id"]

        await db.commit()

        # Trigger deployment
        try:
            deploy_result = await DeploymentService.deploy({
                "id": client.id,
                "name": client.name,
                "email": client.email,
                "company": client.company or "",
                "subdomain": client.subdomain,  # Use pre-reserved subdomain from registration
                "package": client.package,
            })

            # Update client with deployment info
            client.subdomain = deploy_result["subdomain_raw"]
            client.container_port = deploy_result["port"]
            client.container_id = deploy_result["container_id"]
            client.status = "active"
            await db.commit()

            # Update subdomain status from reserved → active
            if deploy_result.get("subdomain_raw"):
                from app.models.subdomain import Subdomain
                sub_result = await db.execute(
                    select(Subdomain).where(Subdomain.subdomain == deploy_result["subdomain_raw"])
                )
                subdomain_record = sub_result.scalar_one_or_none()
                if subdomain_record:
                    subdomain_record.status = "active"
                    subdomain_record.notes = f"Activated via Stripe payment by {client.name}"
                    await db.commit()

            # ── Post-deployment verification ──────────────────────
            verify_result = await DeploymentService.verify_deployment(
                subdomain_raw=deploy_result["subdomain_raw"],
                port=deploy_result["port"],
                container_id=deploy_result["container_id"],
            )

            if not verify_result["ok"]:
                logger.warning(
                    f"⚠️ Deployment verification FAILED for {client.name}: "
                    f"{verify_result['summary']} — {verify_result['errors']}"
                )
                await NotificationService.notify_admin(
                    subject="⚠️ Deployment Verification Failed",
                    body=(
                        f"Deployment completed but verification FAILED:\n"
                        f"• Client: {client.name} ({client.email})\n"
                        f"• Subdomain: {deploy_result['subdomain']}\n"
                        f"• Port: {deploy_result['port']}\n"
                        f"• Container: {deploy_result['container_id']}\n"
                        f"• Summary: {verify_result['summary']}\n"
                        f"• Errors: {chr(10).join(verify_result['errors'])}"
                    ),
                )
                # Still set active — verification is advisory; container may need time
                # Don't block the client; admin will investigate
            else:
                logger.info(f"✅ Deployment verified OK for {client.name} — {verify_result['summary']}")

            # Send notifications
            await DeploymentService.send_deployment_notifications(
                client_id=client.id,
                client_name=client.name,
                client_email=client.email,
                subdomain=deploy_result["subdomain"],
                package=package,
                amount=amount,
            )

        except Exception as deploy_error:
            # Log deployment error, don't fail the webhook
            client.status = "deploy_error"
            await db.commit()

            await NotificationService.notify_admin(
                subject="⚠️ Deployment Failed",
                body=(
                    f"Deployment failed for {client.name} ({client.email}):\n"
                    f"Error: {str(deploy_error)}"
                ),
            )

        return {"status": "success", "client_id": client.id, "package": package}

    return {"status": "ignored", "event_type": event["type"]}


@router.post("/server-b/status")
async def gateway_status_webhook(
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive container status updates from Gateway.

    Payload: { "container_name": "...", "status": "running|stopped|error", "message": "..." }
    """
    # Verify request comes from Gateway
    api_key = request.headers.get("X-API-Key", "")
    if api_key != settings.SERVER_B_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    container_name = data.get("container_name", "")
    status_update = data.get("status", "")
    message = data.get("message", "")

    if not container_name or not status_update:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="container_name and status required")

    # Find client by container
    from sqlalchemy import select
    from app.models.container import Container

    result = await db.execute(
        select(Container).where(Container.container_name == container_name)
    )
    container = result.scalar_one_or_none()

    if container:
        container.status = status_update
        await db.commit()

        # Notify admin if error
        if status_update == "error":
            await NotificationService.notify_admin(
                subject="⚠️ Container Error",
                body=f"Container {container_name} reported error: {message}",
            )

    return {"status": "received"}
