"""
sandbox/local_executor.py

Fallback for when Docker isn't set up yet. Runs the same pytest command
executor.py runs, but directly on the host — no container, no network
isolation, no resource caps, no non-root sandboxing.

Same ExecutionResult output shape as SandboxExecutor, so run_benchmark.py
can use either one interchangeably via sandbox/factory.py.

⚠️ Not a substitute for SandboxExecutor long-term. This is safe for running
YOUR OWN seed tasks (you already trust that code — you wrote it). It stops
being safe the moment agent-generated code you haven't reviewed runs
through it, since there's nothing stopping that code from touching the
network, the filesystem outside the temp dir, or anything else on your
machine. Switch back to the Docker-based executor before Phase 1+ work
involves code you haven't read yet.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from sandbox.executor import ExecutionResult
from sandbox.pytest_output import parse_pytest_output

DEFAULT_TIMEOUT_SECONDS = 30


def _coerce_text(value: bytes | str | None) -> str:
    """
    subprocess.TimeoutExpired.stdout/.stderr are typed as bytes | Any | None
    since the type checker can't see that text=True was passed to
    subprocess.run() above — so this handles both cases explicitly instead
    of relying on an implicit guarantee that could silently break if the
    subprocess call ever changes.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class LocalExecutor:
    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        task_id: str,
        solution_code: str,
        test_code: str,
        solution_filename: str = "solution.py",
        test_filename: str = "test_solution.py",
    ) -> ExecutionResult:
        work_dir = Path(tempfile.mkdtemp(prefix=f"praxis_local_{task_id}_"))
        start = time.monotonic()

        try:
            (work_dir / solution_filename).write_text(solution_code, encoding="utf-8")
            (work_dir / test_filename).write_text(test_code, encoding="utf-8")

            try:
                proc = subprocess.run(
                    ["pytest", "-q", test_filename],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                )
                timed_out = False
                exit_code = proc.returncode
                stdout = proc.stdout + proc.stderr
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                exit_code = None
                stdout = _coerce_text(exc.stdout) + _coerce_text(exc.stderr)

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
            shutil.rmtree(work_dir, ignore_errors=True)