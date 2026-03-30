"""Seed the projects table from PROJECT_REGISTRY config."""
import asyncio

from sqlalchemy import select

from app.config import PROJECT_REGISTRY, settings
from app.database import async_session, engine, Base
from app.models.project import Project


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        for cfg in PROJECT_REGISTRY:
            existing = await session.execute(
                select(Project).where(Project.slug == cfg.slug)
            )
            if existing.scalar_one_or_none():
                print(f"  [skip] {cfg.slug} already exists")
                continue

            api_key = ""
            if cfg.api_key_env:
                api_key = getattr(settings, cfg.api_key_env, "")

            project = Project(
                slug=cfg.slug,
                name=cfg.name,
                business_model=cfg.business_model,
                base_url=cfg.base_url,
                api_key=api_key,
                docker_compose_path=cfg.docker_compose_path,
                docker_project_name=cfg.docker_project_name,
                eval_window_hours=cfg.eval_window_hours,
                eval_cadence_minutes=cfg.eval_cadence_minutes,
                monthly_budget_usd=cfg.monthly_budget_usd,
                status="ACTIVE",
                handles_real_money=cfg.handles_real_money,
                requires_graceful_shutdown=cfg.requires_graceful_shutdown,
            )
            session.add(project)
            print(f"  [added] {cfg.slug}")

        await session.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
