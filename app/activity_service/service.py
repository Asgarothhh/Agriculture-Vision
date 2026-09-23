from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Text, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.tasks_service.models import ProcessingTask
from app.users_service.models import ActivityLog, User

DATE_FULL = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
DATE_DM = re.compile(r"\b(\d{2})\.(\d{2})\b")
DATE_COMPACT = re.compile(r"\b(\d{2})(\d{2})(\d{4})\b")


async def log_event(
    db: AsyncSession,
    user_id: UUID,
    category: str,
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    commit: bool = False,
) -> None:
    db.add(ActivityLog(user_id=user_id, category=category, action=action, payload=payload))
    if commit:
        await db.commit()


def parse_search(q: str) -> tuple[str, list[tuple[int, int, int | None]]]:
    dates: list[tuple[int, int, int | None]] = []
    rest = q
    for match in DATE_COMPACT.finditer(q):
        dates.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
        rest = rest.replace(match.group(0), " ")
    for match in DATE_FULL.finditer(q):
        dates.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
        rest = rest.replace(match.group(0), " ")
    for match in DATE_DM.finditer(rest):
        dates.append((int(match.group(1)), int(match.group(2)), None))
        rest = rest.replace(match.group(0), " ")
    return rest.strip(), dates


async def list_activity(
    db: AsyncSession,
    user: User,
    *,
    category: str | None,
    q: str | None,
    order: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    stmt = select(ActivityLog).where(ActivityLog.user_id == user.id)
    if category:
        stmt = stmt.where(ActivityLog.category == category)
    if q:
        text_part, dates = parse_search(q)
        if text_part:
            like = f"%{text_part}%"
            stmt = stmt.where(
                or_(
                    ActivityLog.action.ilike(like),
                    func.cast(ActivityLog.payload, Text).ilike(like),
                )
            )
        for day, month, year in dates:
            cond = [
                func.extract("day", ActivityLog.created_at) == day,
                func.extract("month", ActivityLog.created_at) == month,
            ]
            if year:
                cond.append(func.extract("year", ActivityLog.created_at) == year)
            stmt = stmt.where(and_(*cond))
    if order == "oldest":
        stmt = stmt.order_by(ActivityLog.created_at.asc())
    else:
        stmt = stmt.order_by(ActivityLog.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "category": row.category,
                "action": row.action,
                "payload": row.payload,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


async def task_for_user(db: AsyncSession, user: User, task_id: UUID) -> ProcessingTask:
    task = (
        await db.execute(
            select(ProcessingTask)
            .options(selectinload(ProcessingTask.image))
            .where(ProcessingTask.id == task_id, ProcessingTask.user_id == user.id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status != "COMPLETED":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Task is not completed")
    return task
