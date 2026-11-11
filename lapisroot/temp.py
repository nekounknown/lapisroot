"""Session orchestration: patch, flash, verify, and restore.

``start`` creates a temporary root session by patching ``init_boot`` with
KernelSU LKM and flashing it.  ``stop`` puts the byte-identical stock image
back.  The journal in :mod:`lapisroot.workspace` is the single source of truth
for what must be restored.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import CODENAME
from . import adb, fastboot, firmware, kernelsu
from .device import Device, Mode, Route, assess, probe
from .errors import DeviceError, LapisRootError, SafetyError
from .proc import Runner, run as _run
from .workspace import Journal, Workspace, sha256_file, utc_now


@dataclass
class StartOptions:
    serial: str | None = None
    stock_image: Path | None = None
    state_dir: Path | None = None
    kmi: str | None = None
    lkm: Path | None = None
    ksu_version: str = "latest"
    variant: str = "KernelSU"
    allow_shell: bool = False
    no_manager: bool = False
    assume_yes: bool = False
    dry_run: bool = False
    runner: Runner = _run


@dataclass
class StopOptions:
    state_dir: Path | None = None
    assume_yes: bool = False
    dry_run: bool = False
    runner: Runner = _run


def _say(message: str = "") -> None:
    print(message)


def _confirm(prompt: str, *, assume_yes: bool, dry_run: bool) -> bool:
    if dry_run or assume_yes:
        return True
    if not sys.stdin.isatty():
        raise SafetyError("refusing to flash in a non-interactive shell; pass --yes")
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def _print_assessment(device: Device | None, assessment) -> None:
    if device is not None:
        for line in device.describe():
            _say(line)
        _say()
    _say(f"route: {assessment.route.value}")
    for reason in assessment.reasons:
        _say(f"- {reason}")
    if assessment.steps:
        _say("next:")
        for step in assessment.steps:
            _say(f"  * {step}")


def _enter_fastboot(device: Device, runner: Runner) -> str:
    if device.mode is Mode.FASTBOOT:
        serial = fastboot.pick_serial(device.serial, runner)
        if serial is None:
            raise DeviceError("the device is no longer visible in fastboot")
        return serial
    _say(f"rebooting {device.serial} to bootloader...")
    adb.reboot(device.serial, "bootloader", runner=runner)
    serial = fastboot.wait_for_fastboot(device.serial, runner=runner, timeout=90.0)
    if serial is None:
        raise DeviceError(
            "the device did not enter fastboot. Hold Volume Down + Power and retry."
        )
    return serial


def _flash_init_boot(
    serial: str,
    image: Path,
    slot: str | None,
    *,
    runner: Runner,
    dry_run: bool,
) -> str:
    partitions = ["init_boot"]
    if slot in ("a", "b"):
        partitions.append(f"init_boot_{slot}")
    last = None
    for partition in partitions:
        result = fastboot.flash(serial, partition, str(image), runner=runner, dry_run=dry_run)
        if result.ok:
            return partition
        last = result
    detail = last.output if last is not None else "no flash attempted"
    raise LapisRootError(f"fastboot flash failed:\n{detail}")


def start(options: StartOptions) -> int:
    workspace = Workspace(options.state_dir)
    workspace.ensure()

    device = probe(options.serial, runner=options.runner)
    assessment = assess(device, options.stock_image)
    _print_assessment(device, assessment)
    _say()

    if assessment.route is not Route.READY:
        if assessment.route is Route.LOCKED:
            return 3
        if assessment.route is Route.NEEDS_STOCK:
            return 4
        return 2

    assert device is not None
    assert options.stock_image is not None

    stock = firmware.materialize(
        options.stock_image, workspace.cache_dir / "firmware", device.boot_partition
    )
    firmware.validate_boot_image(stock, device.boot_partition)

    kmi = options.kmi or device.kmi
    if not kmi:
        _say(
            "error: could not determine the kernel KMI. Connect over adb so "
            "`uname -r` can be read, or pass --kmi android14-6.1."
        )
        return 5

    _say(f"stock image : {stock}")
    _say(f"kmi         : {kmi}")
    _say(f"partition   : {device.boot_partition}")
    _say(f"ksu variant : {options.variant} ({options.ksu_version})")
    _say()

    if options.dry_run:
        _say("dry run: would patch the image with ksud and flash it. Nothing changed.")
        return 0

    if not _confirm(
        "Patch and flash init_boot now? A wrong KMI or image can bootloop the phone.",
        assume_yes=options.assume_yes,
        dry_run=options.dry_run,
    ):
        _say("aborted.")
        return 0

    bundle = kernelsu.prepare(
        options.ksu_version,
        state_dir=workspace.root,
        variant=options.variant,
        fetch_manager=not options.no_manager,
        runner=options.runner,
    )
    _say(f"ksud        : {bundle.version} ({bundle.ksud})")

    patched = kernelsu.patch(
        bundle,
        stock,
        workspace.cache_dir / "patched",
        kmi=kmi,
        lkm=options.lkm,
        allow_shell=options.allow_shell,
        runner=options.runner,
    )
    _say(f"patched     : {patched}")

    serial = _enter_fastboot(device, options.runner)
    slot = fastboot.current_slot(serial, options.runner) or device.slot

    backup, stock_digest = workspace.store_stock(stock)
    journal = Journal(
        serial=serial,
        codename=CODENAME,
        stock_image=str(backup),
        stock_sha256=stock_digest,
        patched_sha256=sha256_file(patched),
        root_version=bundle.version,
        variant=options.variant,
        started_at=utc_now(),
        build=device.build,
        slot=slot,
    )
    workspace.save_journal(journal)

    partition = _flash_init_boot(serial, patched, slot, runner=options.runner, dry_run=False)
    _say(f"flashed {partition}; rebooting...")
    fastboot.reboot(serial, runner=options.runner)

    adb_serial = adb.wait_for_device(serial, runner=options.runner, timeout=150.0)
    if adb_serial is None:
        _say(
            "warning: the phone did not come back on adb. If it is bootlooping, "
            "run `lapisroot stop` from fastboot to restore the stock image."
        )
        return 6

    if not options.no_manager:
        if bundle.manager_apk is not None:
            install = kernelsu.install_manager(
                adb_serial, bundle.manager_apk, runner=options.runner
            )
            if install.ok:
                _say("KernelSU manager installed.")
            else:
                _say("warning: manager install failed; install the APK manually:")
                _say(f"  adb install -r {bundle.manager_apk}")
        elif bundle.manager_error:
            _say(f"warning: manager APK not available: {bundle.manager_error}")

    rooted = kernelsu.check_root(adb_serial, runner=options.runner)
    if rooted:
        _say("root: verified (su -c id -> uid=0).")
    else:
        _say(
            "root: installed, but `su` did not return uid=0 yet. Open the KernelSU "
            "manager app and grant access (or re-run with --allow-shell)."
        )

    _say()
    _say("temporary session active. Revert with: lapisroot stop")
    return 0


def stop(options: StopOptions) -> int:
    workspace = Workspace(options.state_dir)
    journal = workspace.load_journal()
    if journal is None:
        _say("no active session: nothing to restore.")
        return 0

    stock = workspace.stock_from_journal(journal)
    device = probe(journal.serial, runner=options.runner)
    if device is None:
        raise DeviceError("connect the phone over adb or fastboot, then retry")

    _say(f"restoring stock init_boot: {stock}")
    _say(f"session started          : {journal.started_at} ({journal.root_version})")
    if not _confirm(
        "Flash the stock init_boot and reboot?",
        assume_yes=options.assume_yes,
        dry_run=options.dry_run,
    ):
        _say("aborted.")
        return 0

    if options.dry_run:
        _say("dry run: nothing changed.")
        return 0

    serial = _enter_fastboot(device, options.runner)
    slot = fastboot.current_slot(serial, options.runner) or journal.slot
    partition = _flash_init_boot(serial, stock, slot, runner=options.runner, dry_run=False)
    _say(f"restored {partition}; rebooting...")
    fastboot.reboot(serial, runner=options.runner)
    workspace.clear_journal()
    _say("done. The phone is back on the stock init_boot.")
    return 0


def status(options) -> int:
    workspace = Workspace(getattr(options, "state_dir", None))
    device = probe(getattr(options, "serial", None), runner=_run)
    if device is None:
        _say("device: not connected")
    else:
        for line in device.describe():
            _say(line)
    _say()
    journal = workspace.load_journal()
    if journal is None:
        _say("session: none")
        return 0
    _say("session: active")
    _say(f"  started   : {journal.started_at}")
    _say(f"  root      : {journal.root_version} ({journal.variant or 'KernelSU'})")
    _say(f"  build     : {journal.build or '?'}")
    _say(f"  slot      : {journal.slot or '?'}")
    _say(f"  stock     : {journal.stock_image}")
    _say(f"  stock sha : {journal.stock_sha256}")
    return 0


def plan(options) -> int:
    device = probe(getattr(options, "serial", None), runner=_run)
    assessment = assess(device, getattr(options, "stock", None))
    _print_assessment(device, assessment)
    return 0
