"""
Admin users router — user management.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.container import Container
from app.schemas.client import ClientResponse, ClientListResponse
from app.schemas.admin import UserUpdateAdmin, UserCreateAdmin
from app.middleware.auth import get_current_admin
from app.utils.security import hash_password

import logging
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/container-stats")
async def container_stats(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return live vs not-live container counts."""
    from sqlalchemy import func
    total_res = await db.execute(select(func.count(Container.id)))
    total = total_res.scalar() or 0
    live_res = await db.execute(select(func.count(Container.id)).where(Container.status == "running"))
    live = live_res.scalar() or 0
    return {"total": total, "live": live, "not_live": total - live}


@router.get("", response_model=ClientListResponse)
async def list_users(
    search: str = None,
    status_filter: str = None,
    package: str = None,
    skip: int = 0,
    limit: int = 50,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users with optional filters."""
    query = select(Client)

    if search:
        query = query.where(
            Client.name.ilike(f"%{search}%")
            | Client.email.ilike(f"%{search}%")
            | Client.company.ilike(f"%{search}%")
        )
    if status_filter:
        query = query.where(Client.status == status_filter)
    if package:
        query = query.where(Client.package == package)

    query = query.order_by(Client.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    clients = result.scalars().all()

    # Count total
    count_query = select(Client)
    if status_filter:
        count_query = count_query.where(Client.status == status_filter)
    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())

    return ClientListResponse(items=clients, total=total)


@router.post("/", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreateAdmin,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: Create a new user manually."""
    # Check if email already exists
    result = await db.execute(select(Client).where(Client.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    client = Client(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        company=data.company,
        phone=data.phone,
        package=data.package,
        status=data.status,
    )
    db.add(client)
    await db.flush()

    # Create subscription
    sub = Subscription(
        client_id=client.id,
        package=data.package,
        status="active" if data.status == "active" else "pending",
        managed_token_quota=5000000 if data.status == "active" else 0,
        start_date=datetime.now(timezone.utc),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(client)

    return client


@router.get("/{user_id}", response_model=ClientResponse)
async def get_user(
    user_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get user details."""
    result = await db.execute(select(Client).where(Client.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/{user_id}", response_model=ClientResponse)
async def update_user(
    user_id: int,
    data: UserUpdateAdmin,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's details (admin only)."""
    result = await db.execute(select(Client).where(Client.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: Hard-delete a user."""
    result = await db.execute(select(Client).where(Client.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Delete FK children first (Subscription, API keys)
    from app.models.api_key import ApiKey
    await db.execute(select(ApiKey).where(ApiKey.client_id == user_id))
    api_keys = (await db.execute(select(ApiKey).where(ApiKey.client_id == user_id))).scalars().all()
    for ak in api_keys:
        await db.delete(ak)

    sub_result = await db.execute(select(Subscription).where(Subscription.client_id == user_id))
    sub = sub_result.scalar_one_or_none()
    if sub:
        await db.delete(sub)

    await db.delete(user)
    await db.commit()

    return {"message": f"User {user_id} deleted successfully"}


@router.get("/containers/list")
async def list_user_containers(
    client_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List containers for a specific client."""
    result = await db.execute(
        select(Container).where(Container.client_id == client_id).order_by(Container.created_at.desc())
    )
    containers = result.scalars().all()
    return [{
        "id": c.id,
        "name": c.name,
        "container_name": c.container_name,
        "image": c.image,
        "port": c.port,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in containers]


@router.post("/{user_id}/deploy")
async def deploy_user(
    user_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Manually trigger full deployment for a user.
    Uses the user's reserved subdomain, creates container, binds port.
    """
    result = await db.execute(select(Client).where(Client.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Determine subdomain — check client.subdomain first, then subdomains table
    subdomain = user.subdomain
    if not subdomain:
        from app.models.subdomain import Subdomain
        sub_result = await db.execute(
            select(Subdomain).where(
                Subdomain.client_id == user_id,
                Subdomain.status.in_(["reserved", "assigned", "active", "available"])
            )
        )
        sub = sub_result.scalar_one_or_none()
        if sub:
            subdomain = sub.subdomain

    if not subdomain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no subdomain assigned. Create a subdomain first via Subdomains page.",
        )

    # Strip .staffbot.my suffix if present (admin panel stores full domain)
    if subdomain.endswith(".staffbot.my"):
        subdomain = subdomain[:-len(".staffbot.my")]

    # Check if already deployed (has running container)
    container_result = await db.execute(
        select(Container).where(Container.client_id == user_id)
    )
    existing_containers = container_result.scalars().all()
    running = [c for c in existing_containers if c.status == "running"]
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User already has {len(running)} running container(s). Delete them first.",
        )

    # ── Trigger deployment ──────────────────────────────────────
    from app.services.deployment_service import DeploymentService
    from app.services.notification_service import NotificationService

    try:
        deploy_result = await DeploymentService.deploy({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "company": user.company or "",
            "subdomain": subdomain,
            "package": user.package,
        })

        # Update client with deployment info
        user.subdomain = deploy_result["subdomain_raw"]
        user.container_port = deploy_result["port"]
        user.container_id = deploy_result["container_id"]
        user.status = "active"
        await db.commit()

        # Update subdomain status
        from app.models.subdomain import Subdomain as SubdomainModel
        sub_result = await db.execute(
            select(SubdomainModel).where(SubdomainModel.subdomain == deploy_result["subdomain_raw"])
        )
        subdomain_record = sub_result.scalar_one_or_none()
        if subdomain_record:
            subdomain_record.status = "active"
            subdomain_record.notes = f"Manually deployed by admin {admin.name}"
            await db.commit()

        # ── Verification ──────────────────────────────────────────
        verify_result = await DeploymentService.verify_deployment(
            subdomain_raw=deploy_result["subdomain_raw"],
            port=deploy_result["port"],
            container_id=deploy_result["container_id"],
        )

        # Notify admin
        await NotificationService.notify_admin(
            subject="🚀 Manual Deployment Triggered",
            body=(
                f"Admin {admin.name} triggered deployment:\n"
                f"• User: {user.name} ({user.email})\n"
                f"• Subdomain: {deploy_result['subdomain']}\n"
                f"• Port: {deploy_result['port']}\n"
                f"• Container: {deploy_result['container_id']}\n"
                f"• Verification: {verify_result['summary']}"
            ),
        )

        return {
            "status": "success",
            "deployment": {
                "subdomain": deploy_result["subdomain"],
                "port": deploy_result["port"],
                "container_id": deploy_result["container_id"],
            },
            "verification": verify_result,
        }

    except Exception as e:
        logger.error(f"Manual deployment failed for user {user_id}: {e}")
        user.status = "deploy_error"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deployment failed: {str(e)}",
        )
