"""Device probing and routing decisions for the Redmi Note 15 Pro 5G."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import BOOT_PARTITION, CODENAME, MARKETING_NAME, PLATFORM, SOC_NAME
from . import adb, fastboot
from .errors import LapisRootError
from .proc import Runner, run as _run


class Mode(str, Enum):
    ADB = "adb"
    FASTBOOT = "fastboot"
    NONE = "none"


class Route(str, Enum):
    """What the tool can do with the device in its current state."""

    NO_DEVICE = "no-device"
    UNAUTHORIZED = "unauthorized"
    UNSUPPORTED = "unsupported"
    LOCKED = "locked"
    NEEDS_STOCK = "needs-stock"
    READY = "ready"


@dataclass
class Device:
    serial: str
    mode: Mode
    codename: str | None = None
    model: str | None = None
    platform: str | None = None
    android: str | None = None
    build: str | None = None
    slot: str | None = None
    bootloader_locked: bool | None = None
    adb_state: str | None = None
    kernel_release: str | None = None
    props: dict[str, str] = field(default_factory=dict)

    @property
    def kmi(self) -> str | None:
        """GKI KMI (e.g. ``android14-6.1``) derived from ``uname -r``."""
        from .kernelsu import detect_kmi

        return detect_kmi(self.kernel_release)

    @property
    def is_target(self) -> bool:
        codename = (self.codename or "").lower()
        platform = (self.platform or "").lower()
        return codename == CODENAME or platform == PLATFORM

    @property
    def boot_partition(self) -> str:
        return BOOT_PARTITION

    def describe(self) -> list[str]:
        locked = {True: "locked", False: "unlocked", None: "unknown"}[self.bootloader_locked]
        lines = [
            f"serial      : {self.serial}",
            f"mode        : {self.mode.value}"
            + (f" ({self.adb_state})" if self.adb_state else ""),
            f"device      : {self.model or '?'} [{self.codename or '?'}]",
            f"platform    : {self.platform or '?'}",
            f"android     : {self.android or '?'}",
            f"build       : {self.build or '?'}",
            f"kernel      : {self.kernel_release or '?'}",
            f"kmi         : {self.kmi or '?'}",
            f"slot        : {self.slot or '?'}",
            f"bootloader  : {locked}",
        ]
        if self.is_target:
            lines.append(f"target      : yes ({MARKETING_NAME}, {SOC_NAME})")
        else:
            lines.append("target      : NO - this tool only supports " + MARKETING_NAME)
        return lines


def _truthy(value: str | None) -> bool | None:
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("1", "true", "yes", "locked", "green"):
        return True
    if low in ("0", "false", "no", "unlocked", "orange", "yellow"):
        return False
    return None


def _lock_state(props: dict[str, str]) -> bool | None:
    """True means locked.  ``ro.boot.flash.locked`` is authoritative on Xiaomi."""
    if "ro.boot.flash.locked" in props:
        return _truthy(props["ro.boot.flash.locked"])
    if "ro.secureboot.lockstate" in props:
        state = props["ro.secureboot.lockstate"].lower()
        if state == "locked":
            return True
        if state == "unlocked":
            return False
    if "ro.boot.verifiedbootstate" in props:
        return _truthy(props["ro.boot.verifiedbootstate"])
    return None


def _slot_from_props(props: dict[str, str]) -> str | None:
    suffix = props.get("ro.boot.slot_suffix", "")
    if suffix in ("_a", "_b"):
        return suffix[1:]
    slot = props.get("ro.boot.slot")
    if slot in ("a", "b"):
        return slot
    return None


def _device_from_props(serial: str, props: dict[str, str], *, adb_state: str) -> Device:
    return Device(
        serial=serial,
        mode=Mode.ADB,
        codename=(
            props.get("ro.product.device")
            or props.get("ro.product.vendor.device")
            or props.get("ro.build.product")
        ),
        model=props.get("ro.product.model") or props.get("ro.product.vendor.model"),
        platform=props.get("ro.board.platform") or props.get("ro.hardware"),
        android=props.get("ro.build.version.release"),
        build=props.get("ro.build.display.id") or props.get("ro.build.version.incremental"),
        slot=_slot_from_props(props),
        bootloader_locked=_lock_state(props),
        adb_state=adb_state,
        props=props,
    )


def probe(serial: str | None = None, *, runner: Runner = _run) -> Device | None:
    """Find the target device over adb or fastboot.

    Returns ``None`` when nothing is connected.  An adb device that is present
    but not authorized is still returned, with ``adb_state`` set, so the CLI can
    tell the user to accept the RSA prompt.
    """
    adb_entries = adb.list_devices(runner)
    if serial is not None:
        adb_entries = [entry for entry in adb_entries if entry[0] == serial]

    for entry_serial, state in adb_entries:
        if state == "device":
            props = adb.getprop_map(entry_serial, runner)
            device = _device_from_props(entry_serial, props, adb_state=state)
            try:
                uname = adb.shell(entry_serial, "uname", "-r", runner=runner, timeout=15.0)
                device.kernel_release = uname.stdout.strip() or None
            except LapisRootError:
                device.kernel_release = None
            return device
    if adb_entries:
        entry_serial, state = adb_entries[0]
        return Device(serial=entry_serial, mode=Mode.ADB, adb_state=state)

    fb_serial = fastboot.pick_serial(serial, runner)
    if fb_serial is not None:
        values = fastboot.getvars(
            fb_serial,
            ("product", "current-slot", "version", "build", "unlocked"),
            runner,
        )
        unlocked = fastboot.is_unlocked(fb_serial, runner)
        return Device(
            serial=fb_serial,
            mode=Mode.FASTBOOT,
            codename=values.get("product"),
            android=values.get("version"),
            build=values.get("build"),
            slot=values.get("current-slot"),
            bootloader_locked=None if unlocked is None else not unlocked,
            props=values,
        )
    return None


@dataclass
class Assessment:
    route: Route
    device: Device | None
    reasons: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


def assess(device: Device | None, stock_image: Path | None) -> Assessment:
    """Decide which route is available and explain it in plain language."""
    if device is None:
        return Assessment(
            Route.NO_DEVICE,
            None,
            reasons=["No adb or fastboot device detected."],
            steps=[
                "Connect the phone with a data-capable USB-C cable.",
                "Enable Developer options, then USB debugging.",
                "Accept the 'Allow USB debugging' prompt on the phone.",
            ],
        )

    if device.adb_state and (
        device.adb_state.startswith("unauthorized")
        or device.adb_state.startswith("offline")
        or device.adb_state.startswith("no permissions")
        or device.adb_state == "no"
    ):
        return Assessment(
            Route.UNAUTHORIZED,
            device,
            reasons=[f"adb reports the device as '{device.adb_state}'."],
            steps=[
                "Unlock the screen and accept the USB debugging prompt.",
                "If no prompt appears: Developer options -> Revoke USB debugging "
                "authorizations, then replug the cable.",
            ],
        )

    if not device.is_target:
        return Assessment(
            Route.UNSUPPORTED,
            device,
            reasons=[
                f"Connected device is '{device.codename or device.model or 'unknown'}'; "
                f"expected '{CODENAME}'."
            ],
            steps=[f"This tool only supports {MARKETING_NAME} ({CODENAME})."],
        )

    if device.bootloader_locked is not False:
        state = "locked" if device.bootloader_locked else "unknown"
        return Assessment(
            Route.LOCKED,
            device,
            reasons=[f"The bootloader is {state}."],
            steps=[
                "An unlocked bootloader is required: the patched init_boot image "
                "cannot be flashed otherwise.",
                "Apply in the Xiaomi Community app (Global region) and wait out the "
                "72h-30d binding period, then unlock with Mi Unlock.",
                "Re-run `lapisroot plan` once `fastboot getvar unlocked` reports yes.",
                "If you want to check the MediaTek preloader route instead, run "
                "`lapisroot brom probe` (read-only; MT6878 support is incomplete).",
            ],
        )

    if stock_image is None:
        return Assessment(
            Route.NEEDS_STOCK,
            device,
            reasons=["Bootloader is unlocked, but no stock init_boot image was supplied."],
            steps=[
                "Download the fastboot ROM that matches the build currently running.",
                "Pass it with `--stock <rom.tgz|extracted-dir|init_boot.img>`.",
                "Never use an image from a different build: anti-rollback and "
                "AVB will reject or brick the phone.",
            ],
        )

    return Assessment(
        Route.READY,
        device,
        reasons=["Bootloader is unlocked and a stock init_boot image is available."],
        steps=["Run `lapisroot start --stock <image>` to create a temporary root session."],
    )
