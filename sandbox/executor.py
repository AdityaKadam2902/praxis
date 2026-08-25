"""
sandbox/executor.py

The piece everything else in Praxis depends on: turns "the agent says it wrote
working code" into "the code ran, here is exactly what happened."

Design constraints (deliberate, for Phase 0):
  - No network access for the running code (`network_mode="none"`)
  - Hard CPU / memory caps
  - Hard wall-clock timeout
  - Runs as non-root (baked into the sandbox image itself)
  - Container is destroyed immediately after, win or lose — nothing persists

This module has exactly one job: given a task's source code + test file,
return a structured, honest result. It does not talk to any LLM. That's
what makes its output trustworthy as the "outcome" signal in calibration —
it's the one part of the pipeline with no model in the loop.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import docker
from docker.errors import ContainerError, ImageNotFound, APIError

from sandbox.pytest_output import parse_pytest_output

SANDBOX_IMAGE = "praxis-sandbox-runner"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MEMORY_LIMIT = "512m"
DEFAULT_CPU_LIMIT = 1.0  # number of CPUs


@dataclass
class ExecutionResult:
    """Ground-truth outcome of running one task's code against its tests."""

    task_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    wall_time_seconds: float
    tests_collected: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    timed_out: bool = False
    container_error: str | None = None

    @property
    def pass_fraction(self) -> float:
        """
        The core outcome signal fed into calibration fusion.
        1.0 = fully correct, 0.0 = fully wrong or crashed, in between = partial credit.
        """
        if self.timed_out or self.container_error:
            return 0.0
        if self.tests_collected == 0:
            # Nothing to grade against — treat as a hard failure rather than
            # silently scoring 0/0 as success.
            return 0.0
        return self.tests_passed / self.tests_collected

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.container_error


class SandboxExecutor:
    """
    Thin wrapper around the Docker SDK that runs one task per call and
    guarantees cleanup even on crash/timeout.
    """

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
        solution_code: str,
        test_code: str,
        solution_filename: str = "solution.py",
        test_filename: str = "test_solution.py",
    ) -> ExecutionResult:
        """
        Write the agent's solution + the task's held-out tests to a temp dir,
        mount it read-write into a throwaway container, run pytest, capture
        everything, and tear the container down — regardless of outcome.
        """
        work_dir = Path(tempfile.mkdtemp(prefix=f"praxis_{task_id}_"))
        container = None
        start = time.monotonic()

        try:
            (work_dir / solution_filename).write_text(solution_code, encoding="utf-8")
            (work_dir / test_filename).write_text(test_code, encoding="utf-8")

            container_name = f"praxis-run-{uuid.uuid4().hex[:10]}"

            container = self.client.containers.run(
                image=self.image,
                name=container_name,
                command=["pytest", "-q", test_filename],
                working_dir="/home/runner/task",
                volumes={str(work_dir): {"bind": "/home/runner/task", "mode": "rw"}},
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
                # docker-py raises on client-side timeout; the container may
                # still be running on the daemon side, so force-kill it.
                timed_out = True
                exit_code = None
                try:
                    container.kill()
                except APIError:
                    pass

            logs = container.logs(stdout=True, stderr=True).decode(
                "utf-8", errors="replace"
            )
            stdout, stderr = logs, ""  # docker-py interleaves by default here

            collected, passed, failed = parse_pytest_output(stdout)

            return ExecutionResult(
                task_id=task_id,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
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
        except Exception as exc:  # noqa: BLE001 — Phase 0: capture everything, refine later
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
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    # Smoke test — run directly (`python executor.py`) after building the image.
    executor = SandboxExecutor()

    solution = "def add(a, b):\n    return a + b\n"
    tests = (
        "from solution import add\n\n"
        "def test_add_positive():\n    assert add(2, 3) == 5\n\n"
        "def test_add_negative():\n    assert add(-1, -1) == -2\n"
    )

    result = executor.run(task_id="smoke_test_001", solution_code=solution, test_code=tests)
    print(f"succeeded={result.succeeded} pass_fraction={result.pass_fraction:.2f}")
    print(f"tests: {result.tests_passed}/{result.tests_collected} passed")
    print("--- stdout ---")
    print(result.stdout)