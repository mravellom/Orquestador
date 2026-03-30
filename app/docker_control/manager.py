"""Docker container management via python-docker SDK."""
import subprocess

import structlog

logger = structlog.get_logger()


class DockerManager:
    """Manages MVP project containers via docker compose CLI."""

    async def compose_up(self, compose_path: str, project_name: str) -> tuple[bool, str]:
        """Start a project's docker-compose stack."""
        return self._run_compose(compose_path, project_name, "up", "-d")

    async def compose_down(self, compose_path: str, project_name: str) -> tuple[bool, str]:
        """Stop and remove a project's docker-compose stack."""
        return self._run_compose(compose_path, project_name, "down")

    async def compose_pause(self, compose_path: str, project_name: str) -> tuple[bool, str]:
        """Pause a project's containers."""
        return self._run_compose(compose_path, project_name, "pause")

    async def compose_unpause(self, compose_path: str, project_name: str) -> tuple[bool, str]:
        """Unpause a project's containers."""
        return self._run_compose(compose_path, project_name, "unpause")

    async def compose_ps(self, compose_path: str, project_name: str) -> tuple[bool, str]:
        """List containers for a project."""
        return self._run_compose(compose_path, project_name, "ps")

    async def compose_logs(self, compose_path: str, project_name: str, tail: int = 50) -> tuple[bool, str]:
        """Get recent logs for a project."""
        return self._run_compose(compose_path, project_name, "logs", "--tail", str(tail))

    def _run_compose(self, compose_path: str, project_name: str, *args: str) -> tuple[bool, str]:
        """Run a docker compose command. Returns (success, output)."""
        cmd = ["docker", "compose", "-f", f"{compose_path}/docker-compose.yml", "-p", project_name, *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr
            success = result.returncode == 0
            if not success:
                logger.error("Docker compose failed", cmd=" ".join(args), output=output[:500])
            return success, output
        except subprocess.TimeoutExpired:
            logger.error("Docker compose timeout", cmd=" ".join(args))
            return False, "Command timed out"
        except Exception as e:
            logger.error("Docker compose error", cmd=" ".join(args), error=str(e))
            return False, str(e)
