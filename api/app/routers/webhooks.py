"""Webhooks router — handles Stripe payment events including top-ups."""
from fastapi import APIRouter, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends
from datetime import datetime, timezone
from typing import Optional

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.token_topup import TokenTopup, TokenTopupPackage
from app.services.stripe_service import StripeService
from app.services.deployment_service import DeploymentService
from app.services.notification_service import NotificationService
from app.config import get_settings

router = APIRouter()
settings = get_settings()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _handle_subscription_checkout(session: dict, db: AsyncSession):
    """Handle normal subscription checkout — deploy pipeline."""
    metadata = session.get("metadata", {})
    customer_email = metadata.get("customer_email", session.get("customer_email", ""))
    customer_name = metadata.get("customer_name", "")
    package = metadata.get("package", "basic")
    amount = session.get("amount_total", 0) / 100.0

    result = await db.execute(select(Client).where(Client.email == customer_email))
    client = result.scalar_one_or_none()

    if not client:
        client = Client(
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
            start_date=utcnow(),
        )
        db.add(sub)
    else:
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
        })
        client.subdomain = deploy_result["subdomain_raw"]
        client.container_port = deploy_result["port"]
        client.container_id = deploy_result["container_id"]
        client.status = "active"
        await db.commit()

        await DeploymentService.send_deployment_notifications(
            client_id=client.id,
            client_name=client.name,
            client_email=client.email,
            subdomain=deploy_result["subdomain"],
            package=package,
            amount=amount,
        )
    except Exception as deploy_error:
        client.status = "deploy_error"
        await db.commit()
        await NotificationService.notify_admin(
            subject="⚠️ Deployment Failed",
            body=f"Deployment failed for {client.name} ({client.email}):\nError: {str(deploy_error)}",
        )

    return {"status": "success", "client_id": client.id, "package": package}


async def _handle_topup_checkout(session: dict, db: AsyncSession):
    """Handle token top-up checkout — auto-add tokens to user."""
    metadata = session.get("metadata", {})
    client_id = int(metadata.get("client_id", 0))
    package_id = int(metadata.get("package_id", 0))
    tokens = int(metadata.get("tokens", 0))
    amount = session.get("amount_total", 0) / 100.0

    if not client_id:
        return {"status": "error", "message": "No client_id in metadata"}

    # Find client
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        return {"status": "error", "message": f"Client {client_id} not found"}

    # Create top-up record
    topup = TokenTopup(
        client_id=client_id,
        package_id=package_id if package_id > 0 else None,
        tokens=tokens,
        amount_paid=amount,
        stripe_session_id=session["id"],
        status="completed",
        completed_at=utcnow(),
    )
    db.add(topup)

    # ADD tokens to subscription managed quota
    sub_result = await db.execute(
        select(Subscription).where(Subscription.client_id == client_id)
    )
    sub = sub_result.scalar_one_or_none()
    if sub:
        sub.managed_token_quota = (sub.managed_token_quota or 0) + tokens
    else:
        sub = Subscription(
            client_id=client_id,
            package=client.package or "basic",
            status="active",
            managed_token_quota=tokens,
            start_date=utcnow(),
        )
        db.add(sub)

    await db.commit()

    # Notify user via ALL configured channels (WA, Email, SMS, In-app)
    try:
        await NotificationService.notify_client(
            client_id=client_id,
            channels=[],  # Empty = use ALL user's configured channels
            subject="✅ Token Top-Up Successful!",
            body=(
                f"Your token top-up of {tokens:,} tokens has been credited!\n"
                f"Amount paid: RM{amount_paid:.2f}\n"
                f"Your new token balance has been updated."
            ),
        )
    except Exception:
        pass

    return {"status": "success", "client_id": client_id, "tokens_added": tokens}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    event = await StripeService.verify_webhook(payload, sig_header)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})

        # Check if this is a top-up or subscription
        checkout_type = metadata.get("type", "subscription")

        if checkout_type == "topup":
            return await _handle_topup_checkout(session, db)
        else:
            return await _handle_subscription_checkout(session, db)

    return {"status": "ignored", "event_type": event["type"]}


@router.post("/server-b/status")
async def server_b_status_webhook(
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive container status updates from Server B."""
    api_key = request.headers.get("X-API-Key", "")
    if api_key != settings.SERVER_B_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    container_name = data.get("container_name", "")
    status_update = data.get("status", "")
    message = data.get("message", "")

    if not container_name or not status_update:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="container_name and status required")

    from app.models.container import Container
    result = await db.execute(
        select(Container).where(Container.container_name == container_name)
    )
    container = result.scalar_one_or_none()

    if container:
        container.status = status_update
        await db.commit()

        if status_update == "error":
            await NotificationService.notify_admin(
                subject="⚠️ Container Error",
                body=f"Container {container_name} reported error: {message}",
            )

    return {"status": "received"}
