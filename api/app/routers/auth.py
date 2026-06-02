"""
Authentication router.

Endpoints:
- POST /register - Customer signup (creates client + subscription)
- POST /login - Get JWT token
- POST /change-password - Update password (auth required)
- GET /me - Get current user profile
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.schemas.client import ClientCreate, ClientResponse
from app.schemas.auth import Token, PasswordChange
from app.utils.security import hash_password, verify_password, create_access_token
from app.middleware.auth import get_current_client
from app.services.notification_service import NotificationService

router = APIRouter()


@router.post("/register", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def register(client_data: ClientCreate, db: AsyncSession = Depends(get_db)):
    """Register a new customer account."""
    # Check if email already exists
    result = await db.execute(select(Client).where(Client.email == client_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Validate subdomain if provided
    subdomain_name = None
    if client_data.subdomain:
        subdomain_name = client_data.subdomain.strip().lower()
        # Validate format
        import re
        if not re.match(r'^[a-z0-9][a-z0-9\-]{1,38}[a-z0-9]$', subdomain_name):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Subdomain must be 3-40 chars, lowercase letters/numbers/hyphens only, cannot start or end with hyphen",
            )
        # Check uniqueness in subdomains table
        from app.models.subdomain import Subdomain
        sub_result = await db.execute(select(Subdomain).where(Subdomain.subdomain == subdomain_name))
        if sub_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Subdomain '{subdomain_name}.staffbot.my' is already taken. Please choose another.",
            )
        # Also check clients.subdomain column
        client_sub_result = await db.execute(select(Client).where(Client.subdomain == subdomain_name))
        if client_sub_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Subdomain '{subdomain_name}.staffbot.my' is already taken. Please choose another.",
            )

    # Determine package
    package_name = client_data.package or "basic"

    # Create client
    client = Client(
        name=client_data.name,
        email=client_data.email,
        password_hash=hash_password(client_data.password),
        company=client_data.company,
        phone=client_data.phone,
        package=package_name,
        subdomain=subdomain_name,
        status="pending",
    )
    db.add(client)
    await db.flush()

    # Lock subdomain if provided
    if subdomain_name:
        from app.models.subdomain import Subdomain
        subdomain = Subdomain(
            subdomain=subdomain_name,
            client_id=client.id,
            status="reserved",
            notes=f"Reserved during registration by {client_data.name}",
        )
        db.add(subdomain)

    # Create pending subscription — quota from package
    from app.models.package import Package
    pkg_result = await db.execute(select(Package).where(Package.name == package_name))
    pkg = pkg_result.scalar_one_or_none()
    token_quota = pkg.managed_tokens if pkg else 0

    sub = Subscription(
        client_id=client.id,
        package=package_name,
        status="pending",
        managed_token_quota=token_quota,
        start_date=datetime.now(),
    )
    db.add(sub)
    await db.flush()

    # Notify admin about new registration
    subdomain_info = f"\n• Subdomain: {subdomain_name}.staffbot.my" if subdomain_name else ""
    await NotificationService.notify_admin(
        subject="📝 New Registration — StaffBot.my",
        body=(
            f"User Baru Daftar:\n"
            f"• Nama: {client.name}\n"
            f"• Email: {client.email}\n"
            f"• Syarikat: {client.company or '-'}\n"
            f"• Pakej: {client.package.title()}"
            f"{subdomain_info}"
        ),
    )

    await db.commit()
    await db.refresh(client)
    return client


@router.post("/login", response_model=Token)
async def login(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and get access token."""
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email and password required",
        )

    result = await db.execute(select(Client).where(Client.email == email))
    client = result.scalar_one_or_none()

    if not client or not client.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(password, client.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if client.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Please contact support.",
        )

    # Determine role
    from app.config import get_settings
    settings = get_settings()
    role = "admin" if client.email == settings.ADMIN_EMAIL else "customer"

    token = create_access_token(
        data={"sub": client.email, "role": role, "client_id": client.id}
    )
    return Token(access_token=token)


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Change password for authenticated user."""
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"message": "Password updated successfully"}


@router.get("/me", response_model=ClientResponse)
async def get_me(current_user: Client = Depends(get_current_client)):
    """Get current authenticated user's profile."""
    return current_user
