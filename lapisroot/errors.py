"""Typed errors used across lapisroot.

Every failure that the CLI is expected to explain to a human is a
``LapisRootError``.  Unexpected programming errors are allowed to propagate.
"""

from __future__ import annotations


class LapisRootError(Exception):
    """Base class for all expected lapisroot failures."""


class CommandNotFound(LapisRootError):
    """The external binary required for an operation is not installed."""


class CommandTimeout(LapisRootError):
    """An external command exceeded its deadline."""


class CommandFailed(LapisRootError):
    """An external command exited non-zero."""

    def __init__(self, message: str, *, argv: tuple[str, ...] = (), returncode: int = -1,
                 stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class DeviceError(LapisRootError):
    """The device is absent or cannot be talked to."""


class UnsupportedDevice(DeviceError):
    """The connected device is not the model this tool targets."""


class StockImageError(LapisRootError):
    """The stock boot image is missing, malformed or does not match."""


class PatchError(LapisRootError):
    """Magisk boot-image patching failed."""


class SafetyError(LapisRootError):
    """An operation was refused because it would be unsafe."""
