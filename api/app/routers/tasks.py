from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from typing import Optional, List
from app.database import get_db
from app.models.task import Task
from app.models.client import Client
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse
from app.middleware.auth import get_current_client, get_current_client_or_internal

router = APIRouter()


@router.get("/list", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_client_or_internal),
):
    """List all tasks for the current user."""
    query = select(Task).where(Task.client_id == current_user.id)
    
    if status:
        query = query.where(Task.status == status)
    if priority:
        query = query.where(Task.priority == priority)
    if assigned_to:
        query = query.where(Task.assigned_to == assigned_to)
    
    query = query.order_by(Task.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()
    return tasks


@router.post("/create", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_client_or_internal),
):
    """Create a new task."""
    task = Task(
        client_id=current_user.id,
        title=task_data.title,
        description=task_data.description,
        priority=task_data.priority,
        assigned_to=task_data.assigned_to,
        container_id=task_data.container_id,
        created_by_agent=task_data.created_by_agent,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_client_or_internal),
):
    """Get a specific task."""
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.client_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    task_data: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_client_or_internal),
):
    """Update a task."""
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.client_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    update_data = task_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)
    
    await db.flush()
    await db.refresh(task)
    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_client_or_internal),
):
    """Delete a task."""
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.client_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    await db.delete(task)
    return {"success": True, "message": "Task deleted"}


@router.get("/stats/summary")
async def task_stats(
    db: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_client_or_internal),
):
    """Get task statistics."""
    result = await db.execute(
        select(
            func.count(Task.id).label("total"),
            func.count(Task.id).filter(Task.status == "pending").label("pending"),
            func.count(Task.id).filter(Task.status == "in_progress").label("in_progress"),
            func.count(Task.id).filter(Task.status == "completed").label("completed"),
        ).where(Task.client_id == current_user.id)
    )
    row = result.one()
    return {
        "total": row.total,
        "pending": row.pending,
        "in_progress": row.in_progress,
        "completed": row.completed,
    }
