"""fastboot helpers.

fastboot prints ``getvar`` results to stderr on most versions, so every parser
uses ``Result.output`` (stdout + stderr) rather than stdout alone.
"""

from __future__ import annotations

from .proc import Result, Runner, run as _run

FASTBOOT = "fastboot"


def _fb(runner: Runner, *args: str, timeout: float = 20.0) -> Result:
    return runner([FASTBOOT, *args], timeout=timeout)


def list_devices(runner: Runner = _run) -> list[str]:
    result = _fb(runner, "devices", timeout=10.0)
    serials: list[str] = []
    for raw in result.stdout.splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == "fastboot":
            serials.append(fields[0])
    return serials


def pick_serial(serial: str | None = None, runner: Runner = _run) -> str | None:
    serials = list_devices(runner)
    if serial is not None:
        return serial if serial in serials else None
    return serials[0] if serials else None


def getvar(serial: str, name: str, runner: Runner = _run) -> str | None:
    """Return the value of ``fastboot getvar <name>`` or ``None``.

    A non-zero exit code is normal for unknown variables, so the return code is
    intentionally not checked.
    """
    result = _fb(runner, "-s", serial, "getvar", name, timeout=15.0)
    for raw in result.output.splitlines():
        line = raw.strip()
        if line.startswith(f"{name}:"):
            return line.split(":", 1)[1].strip()
    return None


def getvars(serial: str, names: tuple[str, ...], runner: Runner = _run) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in names:
        value = getvar(serial, name, runner)
        if value is not None:
            values[name] = value
    return values


def current_slot(serial: str, runner: Runner = _run) -> str | None:
    value = getvar(serial, "current-slot", runner)
    if value in ("a", "b"):
        return value
    return None


def is_unlocked(serial: str, runner: Runner = _run) -> bool | None:
    """Best-effort bootloader lock state in fastboot mode."""
    unlocked = getvar(serial, "unlocked", runner)
    if unlocked is not None:
        low = unlocked.lower()
        if low in ("yes", "true", "1"):
            return True
        if low in ("no", "false", "0"):
            return False

    info = _fb(runner, "-s", serial, "oem", "device-info", timeout=15.0).output.lower()
    if "device unlocked: true" in info or "unlocked: yes" in info:
        return True
    if "device unlocked: false" in info or "unlocked: no" in info:
        return False
    return None


def flash(serial: str, partition: str, image: str, *, runner: Runner = _run,
          dry_run: bool = False) -> Result:
    if dry_run:
        return Result((FASTBOOT, "-s", serial, "flash", partition, image), 0, "", "")
    return _fb(runner, "-s", serial, "flash", partition, image, timeout=300.0)


def reboot(serial: str, target: str | None = None, *, runner: Runner = _run,
           dry_run: bool = False) -> Result:
    args = ["-s", serial, "reboot"]
    if target:
        args.append(target)
    if dry_run:
        return Result((FASTBOOT, *args), 0, "", "")
    return _fb(runner, *args, timeout=30.0)


def wait_for_fastboot(serial: str | None = None, *, runner: Runner = _run,
                      timeout: float = 90.0) -> str | None:
    """Poll until the device enumerates in fastboot, or return ``None``."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = pick_serial(serial, runner)
        if found is not None:
            return found
        time.sleep(1.0)
    return None
