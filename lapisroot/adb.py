"""adb helpers.

``run`` is injected everywhere so unit tests can supply canned output without
a real adb server.
"""

from __future__ import annotations

from .proc import Result, Runner, run as _run

ADB = "adb"


def _adb(runner: Runner, *args: str, timeout: float = 20.0) -> Result:
    return runner([ADB, *args], timeout=timeout)


def list_devices(runner: Runner = _run) -> list[tuple[str, str]]:
    """Return ``(serial, state)`` pairs from ``adb devices``.

    States include ``device`` (authorized), ``unauthorized``, ``offline`` and
    ``no permissions``.
    """
    result = _adb(runner, "devices", timeout=10.0)
    devices: list[tuple[str, str]] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", "adb server", "List of devices")):
            continue
        # adb separates the serial and state with a tab; anything else is
        # daemon chatter such as "adb server version ... doesn't match".
        if "\t" not in raw:
            continue
        serial, _, state = raw.partition("\t")
        devices.append((serial.strip(), state.strip()))
    return devices


def authorized_serial(runner: Runner = _run, *, preferred: str | None = None) -> str | None:
    """Return an authorized serial, preferring ``preferred`` when given."""
    devices = list_devices(runner)
    if preferred is not None:
        for serial, state in devices:
            if serial == preferred and state == "device":
                return serial
        return None
    for serial, state in devices:
        if state == "device":
            return serial
    return None


def first_state(runner: Runner = _run) -> tuple[str, str] | None:
    """Return the first ``(serial, state)`` regardless of authorization."""
    devices = list_devices(runner)
    return devices[0] if devices else None


def getprop(serial: str, prop: str, runner: Runner = _run) -> str | None:
    result = _adb(runner, "-s", serial, "shell", "getprop", prop, timeout=15.0)
    value = result.stdout.strip()
    return value or None


def getprop_map(serial: str, runner: Runner = _run) -> dict[str, str]:
    """Parse the full ``getprop`` dump into a dict."""
    result = _adb(runner, "-s", serial, "shell", "getprop", timeout=30.0)
    props: dict[str, str] = {}
    for raw in result.stdout.splitlines():
        line = raw.strip()
        # Format: [key]: [value]
        if not line.startswith("[") or "]: [" not in line:
            continue
        key, _, value = line.partition("]: [")
        props[key[1:]] = value[:-1] if value.endswith("]") else value
    return props


def shell(serial: str, *command: str, runner: Runner = _run, timeout: float = 30.0) -> Result:
    return _adb(runner, "-s", serial, "shell", *command, timeout=timeout)


def reboot(serial: str, target: str | None = None, runner: Runner = _run) -> Result:
    args = ["-s", serial, "reboot"]
    if target:
        args.append(target)
    return _adb(runner, *args, timeout=20.0)


def wait_for_device(serial: str | None = None, *, runner: Runner = _run,
                    timeout: float = 120.0) -> str | None:
    """Poll until an authorized adb device appears.

    Bounded polling of real hardware; returns ``None`` on timeout.  Tests call
    this only with a fake runner that reports success immediately.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        serial_found = authorized_serial(runner, preferred=serial)
        if serial_found is not None:
            return serial_found
        time.sleep(1.0)
    return None
