"""Admin subdomains router — CRUD for subdomain management."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.database import get_db
from app.models.client import Client
from app.models.subdomain import Subdomain
from app.schemas.subdomain import SubdomainCreate, SubdomainUpdate, SubdomainResponse
from app.middleware.auth import get_current_admin

router = APIRouter()


async def _enrich(sub: Subdomain, db: AsyncSession) -> dict:
    """Add client_name to subdomain dict."""
    d = {
        "id": sub.id,
        "subdomain": sub.subdomain,
        "client_id": sub.client_id,
        "client_name": None,
        "status": sub.status,
        "notes": sub.notes,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
    }
    if sub.client_id:
        r = await db.execute(select(Client.name).where(Client.id == sub.client_id))
        name = r.scalar_one_or_none()
        d["client_name"] = name
    return d


@router.get("", response_model=list[SubdomainResponse])
async def list_subdomains(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all subdomains."""
    result = await db.execute(select(Subdomain).order_by(Subdomain.created_at.desc()))
    subs = result.scalars().all()
    enriched = []
    for s in subs:
        enriched.append(await _enrich(s, db))
    return enriched


@router.get("/available")
async def available_subdomains(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List available (unassigned) subdomains."""
    result = await db.execute(
        select(Subdomain).where(Subdomain.status == "available").order_by(Subdomain.subdomain)
    )
    subs = result.scalars().all()
    return [{"id": s.id, "subdomain": s.subdomain} for s in subs]


@router.post("", response_model=SubdomainResponse, status_code=status.HTTP_201_CREATED)
async def create_subdomain(
    data: SubdomainCreate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new subdomain."""
    # Strip .staffbot.my suffix if accidentally included
    subdomain_name = data.subdomain
    if subdomain_name.endswith(".staffbot.my"):
        subdomain_name = subdomain_name[:-len(".staffbot.my")]

    # Check uniqueness
    existing = await db.execute(select(Subdomain).where(Subdomain.subdomain == subdomain_name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Subdomain already exists")

    # If assigning to a client, validate client exists
    if data.client_id:
        client_r = await db.execute(select(Client).where(Client.id == data.client_id))
        if not client_r.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Client not found")

    sub = Subdomain(
        subdomain=subdomain_name,
        client_id=data.client_id,
        status=data.status if not data.client_id else "assigned",
        notes=data.notes,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return await _enrich(sub, db)


@router.put("/{subdomain_id}", response_model=SubdomainResponse)
async def update_subdomain(
    subdomain_id: int,
    data: SubdomainUpdate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a subdomain."""
    result = await db.execute(select(Subdomain).where(Subdomain.id == subdomain_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subdomain not found")

    update_data = data.model_dump(exclude_none=True)

    # Strip .staffbot.my suffix if present
    if update_data.get("subdomain") and update_data["subdomain"].endswith(".staffbot.my"):
        update_data["subdomain"] = update_data["subdomain"][:-len(".staffbot.my")]

    # Auto-set status based on client_id
    if "client_id" in update_data:
        if update_data["client_id"]:
            # Validate client
            client_r = await db.execute(select(Client).where(Client.id == update_data["client_id"]))
            client = client_r.scalar_one_or_none()
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")
            update_data["status"] = "assigned"
            # Sync to Client record
            client.subdomain = sub.subdomain
        else:
            update_data["status"] = "available"
            # Remove from old client if any
            if sub.client_id:
                old_client_r = await db.execute(select(Client).where(Client.id == sub.client_id))
                old_client = old_client_r.scalar_one_or_none()
                if old_client:
                    old_client.subdomain = None

    for key, value in update_data.items():
        setattr(sub, key, value)

    await db.commit()
    await db.refresh(sub)
    return await _enrich(sub, db)


@router.delete("/{subdomain_id}")
async def delete_subdomain(
    subdomain_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a subdomain."""
    result = await db.execute(select(Subdomain).where(Subdomain.id == subdomain_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subdomain not found")

    await db.delete(sub)
    await db.commit()
    return {"message": f"Subdomain '{sub.subdomain}' deleted"}
