"""
Tasks and Action Required API endpoints
Manages tasks synced from Zoho CRM and action items for the dashboard
"""
from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.database_models import Task
from app.models.schemas import SuccessResponse

router = APIRouter()


# ============================================
# Action Required (Dashboard)
# ============================================

@router.get("/action-required")
async def get_action_required(
    limit: int = Query(20, le=100),
    include_completed: bool = Query(False),
    db: AsyncSession = Depends(get_db)
):
    """
    Get action required items for the dashboard.
    Returns open tasks sorted by priority and due date.
    Highlights overdue and due-today items.
    """
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # Build query for open tasks
    conditions = []
    if not include_completed:
        conditions.append(Task.status.in_(["pending", "in_progress"]))

    query = select(Task)
    if conditions:
        query = query.where(and_(*conditions))

    # Order by: overdue first, then due today, then by priority, then by due date
    query = query.order_by(
        # Overdue items first (due_date < today and not completed)
        (Task.due_date < today_start).desc(),
        # High priority first
        (Task.priority == "high").desc(),
        # Then by due date ascending (soonest first)
        Task.due_date.asc().nullslast(),
        Task.created_at.desc()
    ).limit(limit)

    result = await db.execute(query)
    tasks = result.scalars().all()

    # Format response with status indicators
    action_items = []
    for task in tasks:
        is_overdue = task.due_date and task.due_date.date() < today if task.due_date else False
        is_due_today = task.due_date and task.due_date.date() == today if task.due_date else False

        action_items.append({
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "is_overdue": is_overdue,
            "is_due_today": is_due_today,
            "assigned_to": task.assigned_to,
            "candidate_name": task.candidate_name,
            "zoho_candidate_id": task.zoho_candidate_id,
            "created_at": task.created_at.isoformat() if task.created_at else None
        })

    # Get counts for summary
    overdue_count = sum(1 for item in action_items if item["is_overdue"])
    due_today_count = sum(1 for item in action_items if item["is_due_today"])
    high_priority_count = sum(1 for item in action_items if item["priority"] == "high")

    return {
        "items": action_items,
        "summary": {
            "total": len(action_items),
            "overdue": overdue_count,
            "due_today": due_today_count,
            "high_priority": high_priority_count
        }
    }


@router.get("/action-required/count")
async def get_action_required_count(db: AsyncSession = Depends(get_db)):
    """Get count of pending action items for badge display"""
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    # Count pending/in_progress tasks
    total_result = await db.execute(
        select(func.count(Task.id))
        .where(Task.status.in_(["pending", "in_progress"]))
    )
    total = total_result.scalar() or 0

    # Count overdue
    overdue_result = await db.execute(
        select(func.count(Task.id))
        .where(and_(
            Task.status.in_(["pending", "in_progress"]),
            Task.due_date < today_start
        ))
    )
    overdue = overdue_result.scalar() or 0

    # Count due today
    today_end = datetime.combine(today, datetime.max.time())
    due_today_result = await db.execute(
        select(func.count(Task.id))
        .where(and_(
            Task.status.in_(["pending", "in_progress"]),
            Task.due_date >= today_start,
            Task.due_date <= today_end
        ))
    )
    due_today = due_today_result.scalar() or 0

    return {
        "total": total,
        "overdue": overdue,
        "due_today": due_today,
        "urgent": overdue + due_today
    }


# ============================================
# Task CRUD
# ============================================

@router.get("/")
async def list_tasks(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """List tasks with optional filters"""
    query = select(Task)

    conditions = []
    if status:
        conditions.append(Task.status == status)
    if priority:
        conditions.append(Task.priority == priority)
    if assigned_to:
        conditions.append(Task.assigned_to == assigned_to)
    if task_type:
        conditions.append(Task.task_type == task_type)

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    tasks = result.scalars().all()

    return [{
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "assigned_to": task.assigned_to,
        "candidate_name": task.candidate_name,
        "zoho_candidate_id": task.zoho_candidate_id,
        "created_at": task.created_at.isoformat() if task.created_at else None
    } for task in tasks]


@router.get("/{task_id}")
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single task by ID"""
    result = await db.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "id": task.id,
        "zoho_task_id": task.zoho_task_id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "assigned_to": task.assigned_to,
        "created_by": task.created_by,
        "candidate_id": task.candidate_id,
        "candidate_name": task.candidate_name,
        "zoho_candidate_id": task.zoho_candidate_id,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None
    }


@router.post("/{task_id}/complete", response_model=SuccessResponse)
async def complete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a task as completed"""
    result = await db.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "completed"
    task.completed_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()

    await db.commit()

    return SuccessResponse(message=f"Task '{task.title}' marked as completed")


@router.post("/{task_id}/reopen", response_model=SuccessResponse)
async def reopen_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Reopen a completed task"""
    result = await db.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "pending"
    task.completed_at = None
    task.updated_at = datetime.utcnow()

    await db.commit()

    return SuccessResponse(message=f"Task '{task.title}' reopened")


# ============================================
# Task Statistics
# ============================================

@router.get("/stats/summary")
async def get_task_stats(db: AsyncSession = Depends(get_db)):
    """Get task statistics"""
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    # Total tasks
    total_result = await db.execute(select(func.count(Task.id)))
    total = total_result.scalar() or 0

    # By status
    pending_result = await db.execute(
        select(func.count(Task.id)).where(Task.status == "pending")
    )
    pending = pending_result.scalar() or 0

    in_progress_result = await db.execute(
        select(func.count(Task.id)).where(Task.status == "in_progress")
    )
    in_progress = in_progress_result.scalar() or 0

    completed_result = await db.execute(
        select(func.count(Task.id)).where(Task.status == "completed")
    )
    completed = completed_result.scalar() or 0

    # Overdue
    overdue_result = await db.execute(
        select(func.count(Task.id))
        .where(and_(
            Task.status.in_(["pending", "in_progress"]),
            Task.due_date < today_start
        ))
    )
    overdue = overdue_result.scalar() or 0

    # By priority (open tasks only)
    high_result = await db.execute(
        select(func.count(Task.id))
        .where(and_(
            Task.status.in_(["pending", "in_progress"]),
            Task.priority == "high"
        ))
    )
    high_priority = high_result.scalar() or 0

    # By type (open tasks only)
    type_query = await db.execute(
        select(Task.task_type, func.count(Task.id))
        .where(Task.status.in_(["pending", "in_progress"]))
        .group_by(Task.task_type)
    )
    by_type = {row[0]: row[1] for row in type_query.all()}

    return {
        "total": total,
        "by_status": {
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed
        },
        "open_tasks": pending + in_progress,
        "overdue": overdue,
        "high_priority": high_priority,
        "by_type": by_type
    }
