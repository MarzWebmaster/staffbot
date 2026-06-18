"""
Admin dashboard router — overview, stats, system health, token usage analytics.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.container import Container
from app.models.token_usage import TokenUsageLog
from app.schemas.admin import DashboardStats, SystemHealth, TokenUsageResponse, TokenUsageSummary, TokenUsagePoint
from app.middleware.auth import get_current_admin
from app.services.server_b_service import GatewayService

router = APIRouter()


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard overview statistics."""
    # Total users
    total_result = await db.execute(select(func.count(Client.id)))
    total_users = total_result.scalar() or 0

    # Active users
    active_result = await db.execute(
        select(func.count(Client.id)).where(Client.status == "active")
    )
    active_users = active_result.scalar() or 0

    # Active containers
    container_result = await db.execute(
        select(func.count(Container.id)).where(Container.status == "running")
    )
    active_containers = container_result.scalar() or 0

    # Pending deployments
    pending_result = await db.execute(
        select(func.count(Container.id)).where(Container.status == "pending")
    )
    pending_deployments = pending_result.scalar() or 0

    # Total revenue (sum of subscription managed_tokens * rate or package prices)
    # For MVP, count active subscriptions with packages
    revenue_result = await db.execute(
        select(func.count(Subscription.id)).where(Subscription.status == "active")
    )
    # Simplified: estimate from active subs
    total_revenue = 0.0

    return DashboardStats(
        total_users=total_users,
        active_users=active_users,
        total_revenue=total_revenue,
        active_containers=active_containers,
        pending_deployments=pending_deployments,
        monthly_revenue=[{"month": "May 2026", "amount": 0}],  # Placeholder
    )


@router.get("/dashboard/token-usage")
async def get_token_usage(
    user_id: Optional[int] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    period: str = "this_month",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = "day",
    limit: int = 50,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get token usage analytics with filters — user, model, period, granularity."""

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── Compute date range ──────────────────────────────────────
    if period == "today":
        range_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        range_end = now
    elif period == "yesterday":
        yesterday = now - timedelta(days=1)
        range_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        range_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == "this_week":
        range_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        range_end = now
    elif period == "last_month":
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        range_end = first_this - timedelta(seconds=1)
        range_start = range_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        range_end = now
    elif period == "custom" and start_date and end_date:
        try:
            range_start = datetime.fromisoformat(start_date)
            range_end = datetime.fromisoformat(end_date)
        except Exception:
            range_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            range_end = now
    else:  # this_month
        range_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        range_end = now

    # ── Build query ──────────────────────────────────────────────
    query = select(TokenUsageLog)
    if user_id:
        query = query.where(TokenUsageLog.client_id == user_id)
    if model:
        query = query.where(TokenUsageLog.model == model)
    if provider:
        query = query.where(TokenUsageLog.provider == provider)
    query = query.where(TokenUsageLog.created_at >= range_start)
    query = query.where(TokenUsageLog.created_at <= range_end)
    query = query.order_by(TokenUsageLog.created_at)

    result = await db.execute(query)
    logs = result.scalars().all()

    # ── Summary ──────────────────────────────────────────────────
    total_tokens = sum(l.total_tokens for l in logs)
    total_input = sum(l.input_tokens for l in logs)
    total_output = sum(l.output_tokens for l in logs)
    total_cost = sum(l.cost for l in logs)
    total_requests = len(logs)
    unique_models = len(set(l.model for l in logs if l.model))
    unique_users = len(set(l.client_id for l in logs))

    # ── Timeseries aggregation ───────────────────────────────────
    if granularity == "hour":
        fmt = "%Y-%m-%d %H:00"
    elif granularity == "week":
        fmt = "%Y-W%W"
    elif granularity == "month":
        fmt = "%Y-%m"
    else:
        fmt = "%Y-%m-%d"

    buckets = defaultdict(
        lambda: {
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "request_count": 0,
        }
    )
    for log in logs:
        key = log.created_at.strftime(fmt)
        buckets[key]["total_tokens"] += log.total_tokens
        buckets[key]["input_tokens"] += log.input_tokens
        buckets[key]["output_tokens"] += log.output_tokens
        buckets[key]["cost"] += log.cost or 0
        buckets[key]["request_count"] += 1

    timeseries = sorted(
        [TokenUsagePoint(date=k, **v) for k, v in buckets.items()],
        key=lambda x: x.date,
    )

    # ── Top models & users ───────────────────────────────────────
    model_buckets: dict[str, int] = defaultdict(int)
    user_buckets: dict[int, int] = defaultdict(int)
    for log in logs:
        if log.model:
            model_buckets[log.model] += log.total_tokens
        user_buckets[log.client_id] += log.total_tokens

    top_models = sorted(
        [{"name": name, "total_tokens": tokens} for name, tokens in model_buckets.items()],
        key=lambda x: x["total_tokens"],
        reverse=True,
    )[:limit]

    top_user_ids = sorted(user_buckets.items(), key=lambda x: x[1], reverse=True)[:limit]
    top_users = []
    for uid, tokens in top_user_ids:
        u_result = await db.execute(select(Client).where(Client.id == uid))
        u = u_result.scalar_one_or_none()
        top_users.append(
            {
                "user_id": uid,
                "name": u.name if u else f"User#{uid}",
                "total_tokens": tokens,
            }
        )

    avg = round(total_tokens / total_requests, 2) if total_requests > 0 else 0.0

    return {
        "summary": {
            "total_tokens": total_tokens,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost": round(total_cost, 6),
            "total_requests": total_requests,
            "avg_tokens_per_request": avg,
            "unique_models": unique_models,
            "unique_users": unique_users,
        },
        "timeseries": [t.model_dump() for t in timeseries],
        "top_models": top_models,
        "top_users": top_users,
    }


@router.get("/health", response_model=SystemHealth)
async def get_system_health(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get system health status."""
    # Check DB
    db_status = "ok"
    try:
        await db.execute(select(func.count(Client.id)).limit(1))
    except Exception:
        db_status = "error"

    # Check Gateway
    try:
        b_health = await GatewayService.health_check()
        gateway_status = b_health.get("status", "unknown")
    except Exception:
        gateway_status = "unreachable"

    return SystemHealth(
        api_status="ok",
        db_status=db_status,
        gateway_status=gateway_status,
        uptime=0.0,  # TODO: track app start time
    )


@router.get("/usage/tokens")
async def get_chart_token_usage(
    period: str = "this_month",
    token_type: str = "all",
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get token usage for dashboard chart, filtered by period + token_type.

    period: today, yesterday, this_week, last_week, this_month, last_month, this_year, all
    token_type: all, provider, managed (provider IS NOT NULL; managed = provider='managed')
    """
    from sqlalchemy import text

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── Compute date range from period ──────────────────────────────
    if period == "today":
        range_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        range_end = now
    elif period == "yesterday":
        yesterday = now - timedelta(days=1)
        range_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        range_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == "this_week":
        range_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        range_end = now
    elif period == "last_week":
        last_week_end = (now - timedelta(days=now.weekday())).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        range_start = (last_week_end - timedelta(days=6)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        range_end = last_week_end
    elif period == "last_month":
        # First day of THIS month minus 1 day = last day of last month
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_of_last_month = first_of_this_month - timedelta(seconds=1)
        range_start = last_of_last_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        range_end = last_of_last_month
    elif period == "this_year":
        range_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        range_end = now
    elif period == "all":
        range_start = datetime(2020, 1, 1)
        range_end = now
    else:  # this_month (default)
        range_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        range_end = now

    # ── Build WHERE clause based on token_type filter ──────────────
    where_clauses = ["created_at >= :start", "created_at <= :end"]
    params: dict = {"start": range_start, "end": range_end}

    if token_type == "provider":
        where_clauses.append("provider IS NOT NULL AND provider != ''")
    elif token_type == "managed":
        where_clauses.append("provider = :managed_provider")
        params["managed_provider"] = "managed"

    where_sql = " AND ".join(where_clauses)

    # ── Pick granularity (day for short ranges, month for long) ────
    days = (range_end - range_start).days
    if days > 180:
        granularity = "month"
        date_trunc = "DATE_TRUNC('month', created_at)"
    elif days > 31:
        granularity = "week"
        date_trunc = "DATE_TRUNC('week', created_at)"
    else:
        granularity = "day"
        date_trunc = "DATE(created_at)"

    query = text(f"""
        SELECT {date_trunc} AS bucket, SUM(total_tokens) AS tokens
        FROM token_usage_log
        WHERE {where_sql}
        GROUP BY bucket
        ORDER BY bucket
    """)

    result = await db.execute(query, params)
    rows = result.all()

    labels = []
    values = []
    for row in rows:
        bucket = row.bucket
        if granularity == "month":
            labels.append(bucket.strftime("%b %Y") if bucket else "N/A")
        elif granularity == "week":
            labels.append(bucket.strftime("%b %d") if bucket else "N/A")
        else:
            labels.append(bucket.strftime("%b %d") if bucket else "N/A")
        values.append(int(row.tokens or 0))

    return {
        "labels": labels,
        "values": values,
        "period": period,
        "token_type": token_type,
        "granularity": granularity,
        "total_tokens": sum(values),
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
    }


@router.get("/activity")
async def get_recent_activity(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get recent user activity for dashboard."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    week_ago = now - timedelta(days=7)
    
    # Get recent registrations
    users_result = await db.execute(
        select(Client).order_by(Client.created_at.desc()).limit(5)
    )
    users = users_result.scalars().all()
    
    # Get recent token usage
    usage_result = await db.execute(
        select(TokenUsageLog).order_by(TokenUsageLog.created_at.desc()).limit(5)
    )
    usage_logs = usage_result.scalars().all()
    
    activities = []
    for u in users:
        activities.append({
            "type": "user_registered",
            "description": f"User {u.name} ({u.email}) registered",
            "timestamp": u.created_at.isoformat() if u.created_at else None,
        })
    
    for log in usage_logs:
        activities.append({
            "type": "token_usage",
            "description": f"Used {log.total_tokens} tokens via {log.provider or 'unknown'}",
            "timestamp": log.created_at.isoformat() if log.created_at else None,
        })
    
    # Sort by timestamp descending
    activities.sort(key=lambda a: a["timestamp"] or "", reverse=True)
    
    return activities[:10]
