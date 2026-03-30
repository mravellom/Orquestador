from pydantic import Field
from pydantic_settings import BaseSettings


class ProjectConfig:
    """Static configuration for each registered MVP project."""

    def __init__(
        self,
        slug: str,
        name: str,
        business_model: str,
        base_url: str,
        docker_compose_path: str,
        docker_project_name: str,
        eval_window_hours: int = 720,
        eval_cadence_minutes: int = 60,
        monthly_budget_usd: float = 0,
        handles_real_money: bool = False,
        requires_graceful_shutdown: bool = False,
        health_endpoint: str = "/health",
        metrics_endpoints: dict[str, str] | None = None,
        api_key_env: str | None = None,
    ):
        self.slug = slug
        self.name = name
        self.business_model = business_model
        self.base_url = base_url
        self.docker_compose_path = docker_compose_path
        self.docker_project_name = docker_project_name
        self.eval_window_hours = eval_window_hours
        self.eval_cadence_minutes = eval_cadence_minutes
        self.monthly_budget_usd = monthly_budget_usd
        self.handles_real_money = handles_real_money
        self.requires_graceful_shutdown = requires_graceful_shutdown
        self.health_endpoint = health_endpoint
        self.metrics_endpoints = metrics_endpoints or {}
        self.api_key_env = api_key_env


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://orquestador:orquestador_secret@db:5432/orquestador"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # MVP API Keys
    acciones_api_key: str = ""
    compraventa_api_key: str = ""
    casas_api_key: str = ""

    # Agent cadences
    monitor_cadence_seconds: int = 30
    estratega_cadence_minutes: int = 10
    reporter_schedule: str = "08:00,20:00"

    # Safety
    kill_requires_human_approval: bool = True
    kill_cooling_period_seconds: int = 300
    max_concurrent_executions: int = 1

    # Docker
    docker_socket: str = "unix:///var/run/docker.sock"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


PROJECT_REGISTRY: list[ProjectConfig] = [
    ProjectConfig(
        slug="acciones",
        name="Acciones Crypto Trading",
        business_model="trading",
        base_url="http://host.docker.internal:8001",
        docker_compose_path="/workspace/Acciones/backend",
        docker_project_name="acciones-backend",
        eval_window_hours=168,
        eval_cadence_minutes=5,
        handles_real_money=True,
        requires_graceful_shutdown=True,
        health_endpoint="/api/v1/system/health",
        metrics_endpoints={
            "portfolio_paper": "/api/v1/portfolio/?mode=PAPER",
            "portfolio_live": "/api/v1/portfolio/?mode=LIVE",
            "analytics": "/api/v1/analytics/summary",
            "risk": "/api/v1/risk/status",
            "pnl": "/api/v1/analytics/pnl?days=30",
            "drawdown": "/api/v1/analytics/drawdown?days=30",
        },
        api_key_env="acciones_api_key",
    ),
    ProjectConfig(
        slug="compraventa",
        name="CompraVenta Arbitrage",
        business_model="arbitrage",
        base_url="http://host.docker.internal:8002",
        docker_compose_path="/workspace/CompraVenta",
        docker_project_name="compraventa",
        eval_window_hours=336,
        eval_cadence_minutes=15,
        health_endpoint="/health",
        metrics_endpoints={
            "opportunities": "/api/v1/opportunities/stats",
            "capital": "/capital/metrics",
            "accuracy": "/api/v1/trades/accuracy?window=7d",
            "pipeline": "/health/pipeline",
        },
        api_key_env="compraventa_api_key",
    ),
    ProjectConfig(
        slug="libro",
        name="Libro KDP Publishing",
        business_model="publishing",
        base_url="http://host.docker.internal:8003",
        docker_compose_path="/workspace/Libro",
        docker_project_name="libro",
        eval_window_hours=2160,
        eval_cadence_minutes=360,
        health_endpoint="/api/metrics",
        metrics_endpoints={
            "metrics": "/api/metrics",
            "analytics": "/api/analytics",
            "risk": "/api/risk",
            "deploy": "/api/deploy/status",
        },
    ),
    # R&D project - no financial rules apply, only output metrics
    ProjectConfig(
        slug="ideas",
        name="GeneradorDeIdeasMuertas",
        business_model="research_lab",
        base_url="http://host.docker.internal:8004",
        docker_compose_path="/workspace/GeneradorDeIdeasMuertas",
        docker_project_name="generadordeideasmuertas",
        eval_window_hours=720,
        eval_cadence_minutes=60,
        health_endpoint="/",
        metrics_endpoints={
            "ideas_list": "/ideas/",
            "ideas_top": "/ideas/top?limit=10",
        },
    ),
    ProjectConfig(
        slug="casas",
        name="Casas InmoAlert Chile",
        business_model="marketplace",
        base_url="http://host.docker.internal:8005",
        docker_compose_path="/workspace/Casas",
        docker_project_name="casas",
        eval_window_hours=336,
        eval_cadence_minutes=30,
        health_endpoint="/api/v1/admin/health",
        metrics_endpoints={
            "metrics": "/api/v1/admin/metrics",
            "feedback": "/api/v1/admin/feedback/stats",
            "opportunities": "/api/v1/opportunities?min_score=70",
        },
        api_key_env="casas_api_key",
    ),
]
