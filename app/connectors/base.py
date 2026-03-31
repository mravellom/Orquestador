"""Base connector with retry, timeout, and circuit breaker."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
import time

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = structlog.get_logger()


@dataclass
class HealthResult:
    is_healthy: bool
    http_status: int | None = None
    response_ms: int | None = None
    database_ok: bool | None = None
    redis_ok: bool | None = None
    details: dict = field(default_factory=dict)
    error_message: str | None = None


@dataclass
class MetricResult:
    metric_type: str = "financial"
    pnl_usd: float | None = None
    roi_pct: float | None = None
    total_capital: float | None = None
    available_capital: float | None = None
    win_rate_pct: float | None = None
    drawdown_pct: float | None = None
    sharpe_ratio: float | None = None
    revenue_usd: float | None = None
    active_users: int | None = None
    items_processed: int | None = None
    false_positive_rate: float | None = None
    raw_data: dict = field(default_factory=dict)


@dataclass
class ActionResult:
    success: bool
    message: str = ""
    details: dict = field(default_factory=dict)


class BaseConnector:
    """HTTP connector with retry and circuit breaker for an MVP project."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._consecutive_failures = 0
        self._circuit_open_until: datetime | None = None

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until and datetime.now(UTC) < self._circuit_open_until:
            return True
        if self._circuit_open_until and datetime.now(UTC) >= self._circuit_open_until:
            self._circuit_open_until = None
        return False

    def _record_success(self):
        self._consecutive_failures = 0
        self._circuit_open_until = None

    def _record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= 5:
            self._circuit_open_until = datetime.now(UTC) + timedelta(seconds=60)
            logger.warning("Circuit breaker opened", base_url=self.base_url)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def _get(self, path: str) -> httpx.Response:
        if self._is_circuit_open():
            raise httpx.ConnectError(f"Circuit breaker open for {self.base_url}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = f"{self.base_url}{path}"
            response = await client.get(url, headers=self._headers())
            return response

    async def _safe_get(self, path: str) -> tuple[httpx.Response | None, int]:
        """GET with timing. Returns (response, elapsed_ms)."""
        start = time.monotonic()
        try:
            resp = await self._get(path)
            elapsed = int((time.monotonic() - start) * 1000)
            self._record_success()
            return resp, elapsed
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            self._record_failure()
            logger.error("Connector request failed", url=f"{self.base_url}{path}", error=str(e))
            return None, elapsed

    async def check_health(self) -> HealthResult:
        raise NotImplementedError

    async def collect_metrics(self) -> MetricResult:
        raise NotImplementedError

    async def execute_action(self, action: str, params: dict | None = None) -> ActionResult:
        raise NotImplementedError
