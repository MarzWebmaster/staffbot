import os
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.client import Client
from app.utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

GATEWAY_INTERNAL_KEY = os.getenv("GATEWAY_API_KEY", "hermes-gateway-key-2024-secure")


async def get_current_client(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Client:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("sub")
    role = payload.get("role")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(Client).where(Client.email == email))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client not found",
        )

    if client.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended",
        )

    return client


async def get_current_admin(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Client:
    client = await get_current_client(token, db)
    # Simple admin check: email matches configured admin email
    from app.config import get_settings
    settings = get_settings()
    if client.email != settings.ADMIN_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return client


async def get_current_client_or_internal(
    request: Request,
    token: str = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Client:
    """
    Authenticate via JWT (Bearer token) OR internal gateway key.

    Internal gateway tools use:
      - X-Internal-Key: the shared gateway secret
      - X-Client-ID: the client ID to impersonate
    """
    # Try internal gateway auth first
    internal_key = request.headers.get("X-Internal-Key")
    client_id_str = request.headers.get("X-Client-ID")

    if internal_key and internal_key == GATEWAY_INTERNAL_KEY and client_id_str:
        try:
            client_id = int(client_id_str)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid X-Client-ID")

        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if client is None:
            raise HTTPException(status_code=401, detail="Client not found")
        if client.status == "suspended":
            raise HTTPException(status_code=403, detail="Account suspended")
        return client

    # Fall back to JWT auth
    if token:
        return await get_current_client(token, db)
    raise HTTPException(status_code=401, detail="Not authenticated")
