"""Thin, testable wrapper around ``subprocess``.

All external commands in lapisroot go through :func:`run`.  Tests replace it
with a fake that dispatches on ``argv``, which keeps the rest of the code free
of subprocess plumbing.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .errors import CommandFailed, CommandNotFound, CommandTimeout

DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class Result:
    """Captured result of an external command."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        """stdout and stderr merged, which is what adb/fastboot parsers need."""
        parts = [self.stdout.strip(), self.stderr.strip()]
        return "\n".join(part for part in parts if part)


Runner = Callable[..., Result]


def which(name: str) -> str | None:
    """Return the absolute path of ``name`` on PATH, or ``None``."""
    return shutil.which(name)


def run(
    argv: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    input: str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    check: bool = False,
) -> Result:
    """Execute ``argv`` and capture its output.

    ``FileNotFoundError`` and ``TimeoutExpired`` are translated into typed
    errors so callers never have to catch OSError subclasses.
    """
    args = [str(a) for a in argv]
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            input=input,
            env=None if env is None else dict(env),
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        raise CommandNotFound(f"{args[0]}: command not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeout(
            f"`{' '.join(args)}` did not finish within {timeout:g}s"
        ) from exc

    result = Result(
        argv=tuple(args),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    if check and not result.ok:
        raise CommandFailed(
            f"`{' '.join(args)}` exited {result.returncode}",
            argv=result.argv,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result
