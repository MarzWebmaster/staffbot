"""
Admin dashboard router — overview, stats, system health, usage tracking, staff list, activity.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.container import Container
from app.models.usage_log import UsageLog
from app.schemas.admin import DashboardStats, SystemHealth, TokenUsageData, UsageByClient, ActivityItem, StaffItem
from app.middleware.auth import get_current_admin
from app.services.server_b_service import ServerBService

router = APIRouter()


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard overview statistics."""
    total_result = await db.execute(select(func.count(Client.id)))
    total_users = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count(Client.id)).where(Client.status == "active")
    )
    active_users = active_result.scalar() or 0

    container_result = await db.execute(
        select(func.count(Container.id)).where(Container.status == "running")
    )
    active_containers = container_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(Client.id)).where(Client.status == "pending")
    )
    pending_deployments = pending_result.scalar() or 0

    total_revenue = 0.0

    return DashboardStats(
        total_users=total_users,
        active_users=active_users,
        total_revenue=total_revenue,
        active_containers=active_containers,
        pending_deployments=pending_deployments,
        monthly_revenue=[{"month": "May 2026", "amount": 0}],
    )


@router.get("/health", response_model=SystemHealth)
async def get_system_health(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    db_status = "ok"
    try:
        await db.execute(select(func.count(Client.id)).limit(1))
    except Exception:
        db_status = "error"

    try:
        b_health = await ServerBService.health_check()
        server_b_status = b_health.get("status", "unknown")
    except Exception:
        server_b_status = "unreachable"

    return SystemHealth(
        api_status="ok",
        db_status=db_status,
        server_b_status=server_b_status,
        uptime=0.0,
    )


@router.get("/usage/tokens", response_model=TokenUsageData)
async def get_token_usage(
    days: int = Query(7, ge=1, le=90),
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get token usage data for the last N days for charts."""
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    from collections import defaultdict

    from sqlalchemy import text
    # Use raw SQL to avoid PostgreSQL strict GROUP BY issues with date_trunc
    rows = await db.execute(
        text("""
            SELECT date_trunc('day', created_at) AS day,
                   SUM(total_tokens) AS tokens
            FROM usage_logs
            WHERE created_at >= :since
            GROUP BY date_trunc('day', created_at)
            ORDER BY date_trunc('day', created_at)
        """),
        {"since": since}
    )
    daily_map = defaultdict(int)
    for row in rows.all():
        day_key = row.day.strftime("%Y-%m-%d") if row.day else ""
        daily_map[day_key] = row.tokens or 0

    labels = []
    values = []
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        labels.append(d)
        values.append(daily_map.get(d, 0))

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    active = await db.execute(
        select(func.count(func.distinct(UsageLog.client_id)))
        .where(UsageLog.created_at >= today_start)
    )
    active_clients = active.scalar() or 0

    total_calls = await db.execute(
        select(func.count(UsageLog.id))
        .where(UsageLog.created_at >= since)
    )
    total_tokens = sum(values)
    total_calls_count = total_calls.scalar() or 1
    avg_per_call = total_tokens // max(total_calls_count, 1)

    return TokenUsageData(
        labels=labels,
        values=values,
        active_clients=active_clients,
        avg_per_call=avg_per_call,
    )


@router.get("/usage/by-client")
async def get_usage_by_client(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get token usage grouped by client."""
    rows = await db.execute(
        select(
            UsageLog.client_id,
            UsageLog.client_name,
            UsageLog.package,
            func.sum(UsageLog.total_tokens).label("tokens"),
            func.count(UsageLog.id).label("calls"),
        )
        .group_by(UsageLog.client_id, UsageLog.client_name, UsageLog.package)
        .order_by(desc(func.sum(UsageLog.total_tokens)))
        .limit(50)
    )
    items = []
    for row in rows.all():
        items.append({
            "id": row.client_id,
            "name": row.client_name or f"Client #{row.client_id}",
            "package": row.package or "basic",
            "tokens": row.tokens or 0,
            "calls": row.calls or 0,
        })
    return {"items": items}


@router.post("/usage/record")
async def record_usage(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Record token usage from Hermes containers. Internal endpoint."""
    log = UsageLog(
        client_id=data.get("client_id", 0),
        client_name=data.get("client_name", ""),
        container_id=data.get("container_id"),
        package=data.get("package", "basic"),
        tokens_in=data.get("tokens_in", 0),
        tokens_out=data.get("tokens_out", 0),
        total_tokens=data.get("total_tokens", 0),
        model=data.get("model", ""),
        endpoint=data.get("endpoint", "chat"),
        status=data.get("status", "success"),
    )
    db.add(log)
    await db.flush()
    return {"status": "ok", "id": log.id}


@router.get("/activity", response_model=ActivityItem)
async def get_recent_activity(
    limit: int = Query(10, ge=1, le=50),
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get recent activity for the dashboard."""
    rows = await db.execute(
        select(UsageLog)
        .order_by(desc(UsageLog.created_at))
        .limit(limit)
    )
    items = []
    for log in rows.scalars().all():
        items.append({
            "icon": "🤖",
            "action": f"AI call ({log.model or 'unknown'})",
            "detail": f"{log.client_name} | {log.total_tokens} tokens" if log.total_tokens else (log.client_name or ""),
            "time": log.created_at.strftime("%d %b %H:%M") if log.created_at else "",
        })
    return {"items": items}


@router.get("/staff", response_model=StaffItem)
async def get_staff_list(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get list of AI staff (clients with containers)."""
    rows = await db.execute(
        select(Client, Container)
        .outerjoin(Container, Container.client_id == Client.id)
        .order_by(Client.id)
    )
    items = []
    for client, container in rows.all():
        items.append({
            "id": client.id,
            "name": f"AI Staff - {client.name or 'Client #' + str(client.id)}",
            "client_name": client.name or f"Client #{client.id}",
            "status": container.status if container else "pending",
            "package": client.package or "basic",
            "container_id": container.id if container else None,
        })
    return {"items": items}
