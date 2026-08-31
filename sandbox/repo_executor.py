"""
sandbox/repo_executor.py

Repo-level grounding, Docker variant — same isolation approach as
executor.py (network-less, resource-capped, non-root), but mounts an
already-prepared repo directory (git_ops.write_files + commit already
done) instead of writing a single solution+test pair into a fresh temp
dir.

Reuses the same sandbox image built in Phase 0 (praxis-sandbox-runner) —
it only needs Python + pytest, which the current seed repo doesn't
exceed. If a future seed repo needs its own dependencies (a
requirements.txt), the image or a dependency-install step will need to
grow to match — not handled yet, flagged here rather than silently
assumed away.

Note: this path (PRAXIS_SANDBOX=docker) hasn't been exercised in this
project yet — development has stayed on the local/no-Docker path so far,
same as Phase 0's original executor.py. Written to the same standard and
following the exact pattern that's already proven out in executor.py,
but worth an explicit test run before relying on it.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import docker
from docker.errors import ContainerError, ImageNotFound, APIError

from sandbox.result import ExecutionResult, SANDBOX_IMAGE
from sandbox.pytest_output import parse_pytest_output

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MEMORY_LIMIT = "512m"
DEFAULT_CPU_LIMIT = 1.0


class RepoSandboxExecutor:
    def __init__(
        self,
        image: str = SANDBOX_IMAGE,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        cpu_limit: float = DEFAULT_CPU_LIMIT,
    ) -> None:
        self.client = docker.from_env()
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit

        try:
            self.client.images.get(self.image)
        except ImageNotFound as exc:
            raise RuntimeError(
                f"Sandbox image '{self.image}' not found. Build it first: "
                f"docker build -f sandbox/Dockerfile.runner -t {self.image} ./sandbox"
            ) from exc

    def run(
        self,
        task_id: str,
        repo_dir: str,
        test_command: list[str] | None = None,
    ) -> ExecutionResult:
        command = test_command or ["pytest", "-q"]
        container = None
        start = time.monotonic()

        try:
            container_name = f"praxis-repo-run-{uuid.uuid4().hex[:10]}"

            container = self.client.containers.run(
                image=self.image,
                name=container_name,
                command=command,
                working_dir="/home/runner/task",
                volumes={
                    str(Path(repo_dir).resolve()): {"bind": "/home/runner/task", "mode": "rw"}
                },
                network_mode="none",
                mem_limit=self.memory_limit,
                nano_cpus=int(self.cpu_limit * 1e9),
                user="runner",
                detach=True,
                stdout=True,
                stderr=True,
            )

            timed_out = False
            try:
                exit_status = container.wait(timeout=self.timeout_seconds)
                exit_code = exit_status.get("StatusCode")
            except Exception:
                timed_out = True
                exit_code = None
                try:
                    container.kill()
                except APIError:
                    pass

            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            stdout = logs

            collected, passed, failed = parse_pytest_output(stdout)

            return ExecutionResult(
                task_id=task_id,
                exit_code=exit_code,
                stdout=stdout,
                stderr="",
                wall_time_seconds=time.monotonic() - start,
                tests_collected=collected,
                tests_passed=passed,
                tests_failed=failed,
                timed_out=timed_out,
            )

        except ContainerError as exc:
            return ExecutionResult(
                task_id=task_id,
                exit_code=exc.exit_status,
                stdout="",
                stderr=str(exc),
                wall_time_seconds=time.monotonic() - start,
                container_error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 — mirror executor.py's fail-safe behavior
            return ExecutionResult(
                task_id=task_id,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                wall_time_seconds=time.monotonic() - start,
                container_error=str(exc),
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except APIError:
                    pass