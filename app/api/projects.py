"""Projects API - CRUD for project registry."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.project import Project
from app.schemas.project import ProjectOut, ProjectUpdate

router = APIRouter()


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project))
    return result.scalars().all()


@router.get("/projects/{slug}")
async def get_project(slug: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.slug == slug))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/projects/{slug}")
async def update_project(slug: str, update: ProjectUpdate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.slug == slug))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    await session.commit()
    await session.refresh(project)
    return project


@router.post("/projects/{slug}/pause")
async def pause_project(slug: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.slug == slug))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.status = "PAUSED"
    await session.commit()
    return {"slug": slug, "status": "PAUSED"}


@router.post("/projects/{slug}/resume")
async def resume_project(slug: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.slug == slug))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.status = "ACTIVE"
    await session.commit()
    return {"slug": slug, "status": "ACTIVE"}
