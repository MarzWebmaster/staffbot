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
