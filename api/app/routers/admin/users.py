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


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
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

    # Look up package token quota
    from app.models.package import Package
    pkg_result = await db.execute(select(Package).where(Package.name == data.package))
    pkg = pkg_result.scalar_one_or_none()
    token_quota = pkg.managed_tokens if pkg else 0

    # Create subscription
    sub = Subscription(
        client_id=client.id,
        package=data.package,
        status="active" if data.status == "active" else "pending",
        managed_token_quota=token_quota if data.status == "active" else 0,
        start_date=datetime.now(timezone.utc).replace(tzinfo=None),
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
    old_package = user.package
    for key, value in update_data.items():
        setattr(user, key, value)

    # If package changed, sync subscription
    if 'package' in update_data and update_data['package'] != old_package:
        sub_result = await db.execute(
            select(Subscription).where(Subscription.client_id == user_id)
        )
        sub = sub_result.scalar_one_or_none()
        if sub:
            from app.models.package import Package
            pkg_result = await db.execute(
                select(Package).where(Package.name == update_data['package'])
            )
            pkg = pkg_result.scalar_one_or_none()
            sub.package = update_data['package']
            sub.managed_token_quota = pkg.managed_tokens if pkg else sub.managed_token_quota

            # Hot-reload gateway profile (no restart needed)
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as client:
                    await client.post(
                        f"http://staffbot-gateway:8080/admin/reload-profile",
                        json={"client_id": user_id, "package": update_data["package"]},
                    )
                logger.info(f"Gateway profile reloaded for user #{user_id} → {update_data['package']}")
            except Exception as e:
                logger.warning(f"Gateway reload skipped for user #{user_id}: {e}")

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: Hard-delete a user with full cascade cleanup."""
    from sqlalchemy import text
    result = await db.execute(select(Client).where(Client.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(f"Cascade deleting user {user_id} ({user.email})")

    # 1. Delete client_memory (personal AI memory)
    mem_result = await db.execute(text("DELETE FROM client_memory WHERE client_id = :cid"), {"cid": user_id})
    logger.info(f"  Deleted {mem_result.rowcount} client_memory records")

    # 2. Delete memory_audit_log
    await db.execute(text("DELETE FROM memory_audit_log WHERE client_id = :cid"), {"cid": user_id})

    # 3. Delete notifications
    await db.execute(text("DELETE FROM notifications_log WHERE client_id = :cid"), {"cid": user_id})
    await db.execute(text("DELETE FROM notification_channels WHERE client_id = :cid"), {"cid": user_id})

    # 4. Delete scheduled tasks
    await db.execute(text("DELETE FROM tasks WHERE client_id = :cid"), {"cid": user_id})

    # 5. Delete affiliates
    await db.execute(text("DELETE FROM affiliates WHERE client_id = :cid"), {"cid": user_id})

    # 6. Delete subdomains
    await db.execute(text("DELETE FROM subdomains WHERE client_id = :cid"), {"cid": user_id})

    # 7. Delete token_topups
    await db.execute(text("DELETE FROM token_topups WHERE client_id = :cid"), {"cid": user_id})

    # 8. Stop and remove Docker containers for this user
    from app.services.docker_service import DockerService
    containers = (await db.execute(select(Container).where(Container.client_id == user_id))).scalars().all()
    for c in containers:
        try:
            DockerService.stop_container(c.container_name)
            DockerService.remove_container(c.container_name)
            logger.info(f"  Removed container: {c.container_name}")
        except Exception as e:
            logger.warning(f"  Failed to remove container {c.container_name}: {e}")
        await db.delete(c)

    # 9. Delete API keys
    from app.models.api_key import ApiKey
    api_keys = (await db.execute(select(ApiKey).where(ApiKey.client_id == user_id))).scalars().all()
    for ak in api_keys:
        await db.delete(ak)

    # 10. Delete subscription
    sub_result = await db.execute(select(Subscription).where(Subscription.client_id == user_id))
    sub = sub_result.scalar_one_or_none()
    if sub:
        await db.delete(sub)

    # 11. Anonymize business data (KEEP for analytics, strip PII)
    await db.execute(text(
        "UPDATE chat_messages SET content = '[deleted]' WHERE client_id = :cid"
    ), {"cid": user_id})

    # 12. Delete the user
    await db.delete(user)
    await db.commit()

    logger.info(f"User {user_id} fully deleted with cascade cleanup")
    return {"message": f"User {user_id} deleted successfully with all associated data"}


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

        # Create container record in containers table
        container_record = Container(
            client_id=user.id,
            name="AI Staff 1",
            container_name=deploy_result.get("container_name", f"staffbot-{deploy_result['subdomain_raw']}"),
            image="staffbot-core:latest",
            port=deploy_result["port"],
            status="running",
            skills=["chat", "memory", "tasks"],
        )
        db.add(container_record)
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


@router.get("/{user_id}/token-usage")
async def get_user_token_usage(
    user_id: int,
    period: str = "daily",
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get token usage stats + time series for a specific user."""
    from sqlalchemy import func, text
    from app.models.token_usage import TokenUsageLog

    # Verify user exists
    result = await db.execute(select(Client).where(Client.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Get subscription info
    sub_result = await db.execute(
        select(Subscription).where(Subscription.client_id == user_id)
    )
    sub = sub_result.scalar_one_or_none()

    managed_quota = (sub.managed_token_quota or 0) if sub else 0
    managed_used = (sub.managed_token_used or 0) if sub else 0

    # Total tokens used (all-time from logs)
    total_result = await db.execute(
        select(func.coalesce(func.sum(TokenUsageLog.total_tokens), 0)).where(
            TokenUsageLog.client_id == user_id
        )
    )
    total_used = total_result.scalar() or 0

    # Time series based on period
    trunc = {
        "daily": "day",
        "monthly": "month",
        "yearly": "year",
    }.get(period, "day")

    time_result = await db.execute(
        text(f"""
            SELECT 
                DATE_TRUNC('{trunc}', created_at) AS period,
                COALESCE(SUM(total_tokens), 0)::bigint AS tokens,
                COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                COALESCE(SUM(cost), 0)::float AS cost,
                COUNT(*)::integer AS requests
            FROM token_usage_log
            WHERE client_id = :cid
            GROUP BY DATE_TRUNC('{trunc}', created_at)
            ORDER BY period DESC
            LIMIT 90
        """),
        {"cid": user_id}
    )
    rows = time_result.fetchall()

    timeseries = [
        {
            "period": str(r[0]),
            "tokens": r[1],
            "input_tokens": r[2],
            "output_tokens": r[3],
            "cost": round(r[4], 4),
            "requests": r[5],
        }
        for r in rows
    ]

    # Top models for this user
    model_result = await db.execute(
        select(
            TokenUsageLog.model,
            func.sum(TokenUsageLog.total_tokens).label("tokens"),
            func.count().label("requests"),
        )
        .where(TokenUsageLog.client_id == user_id)
        .group_by(TokenUsageLog.model)
        .order_by(func.sum(TokenUsageLog.total_tokens).desc())
        .limit(5)
    )
    top_models = [
        {"model": r[0], "tokens": int(r[1]), "requests": r[2]}
        for r in model_result.fetchall()
    ]

    return {
        "client_id": user_id,
        "total_used": total_used,
        "managed_quota": managed_quota,
        "managed_used": managed_used,
        "balance": max(0, managed_quota - managed_used),
        "timeseries": timeseries,
        "top_models": top_models,
    }
