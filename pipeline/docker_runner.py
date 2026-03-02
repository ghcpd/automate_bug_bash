"""Docker container lifecycle helpers for pipeline verification steps."""
from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path
from typing import Optional

import docker
from docker.errors import BuildError, ContainerError, ImageNotFound


class DockerRunner:
    """Manage ephemeral Docker containers for repo verification.

    Usage::

        runner = DockerRunner()
        result = runner.run_setup_and_test(
            image_tag="tb-verify/owner__repo__abc123",
            setup_cmd='pip install -e ".[dev,test]" --quiet',
            test_cmd="python -m pytest --tb=no -q 2>&1",
            timeout=1200,
        )
    """

    def __init__(self) -> None:
        self.client = docker.from_env()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_image(self, dockerfile_content: str, tag: str,
                    timeout: int = 600) -> str:
        """Build a Docker image from a Dockerfile string and return the tag."""
        fileobj = io.BytesIO(dockerfile_content.encode())
        try:
            image, _ = self.client.images.build(
                fileobj=fileobj,
                tag=tag,
                rm=True,
                forcerm=True,
                timeout=timeout,
            )
            return tag
        except BuildError as exc:
            lines = [
                line.get("stream", line.get("error", ""))
                for line in exc.build_log
            ]
            # Cap to last 50 lines to avoid overwhelming error messages
            tail = "".join(lines[-50:]).strip()
            raise RuntimeError(f"Docker build failed for {tag}:\n{tail}") from exc

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run_commands(
        self,
        image: str,
        commands: list[str],
        workdir: str = "/app",
        timeout: int = 1200,
        network_disabled: bool = True,
    ) -> dict:
        """Run a sequence of shell commands in a fresh container.

        Returns::

            {
                "exit_code": int,
                "stdout": str,
                "stderr": str,
                "elapsed_sec": float,
            }
        """
        full_cmd = " && ".join(commands)
        start = time.monotonic()
        try:
            container = self.client.containers.run(
                image,
                command=["bash", "-c", full_cmd],
                working_dir=workdir,
                network_disabled=network_disabled,
                detach=True,
                remove=False,
            )
            try:
                result = container.wait(timeout=timeout)
                logs = container.logs(stdout=True, stderr=True).decode(
                    "utf-8", errors="replace"
                )
                return {
                    "exit_code": result["StatusCode"],
                    "stdout": logs,
                    "stderr": "",
                    "elapsed_sec": time.monotonic() - start,
                }
            except Exception as exc:
                container.stop(timeout=5)
                raise TimeoutError(
                    f"Container exceeded {timeout}s timeout"
                ) from exc
            finally:
                container.remove(force=True)
        except ImageNotFound:
            raise RuntimeError(f"Docker image not found: {image}")

    def try_setup_strategies(
        self,
        image: str,
        strategies: list[str],
        workdir: str = "/app",
        timeout_per_strategy: int = 300,
    ) -> tuple[Optional[str], float, str]:
        """Attempt each setup strategy in order; return (winning_cmd, elapsed, logs).

        Returns (None, 0.0, last_logs) if all strategies fail.
        """
        last_logs = ""
        for cmd in strategies:
            result = self.run_commands(
                image,
                [cmd],
                workdir=workdir,
                timeout=timeout_per_strategy,
                network_disabled=False,  # setup needs internet
            )
            last_logs = result["stdout"]
            if result["exit_code"] == 0:
                return cmd, result["elapsed_sec"], last_logs
        return None, 0.0, last_logs

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def remove_image(self, tag: str, force: bool = False) -> None:
        try:
            self.client.images.remove(tag, force=force)
        except ImageNotFound:
            pass
