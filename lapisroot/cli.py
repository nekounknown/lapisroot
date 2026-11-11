"""Command line interface for lapisroot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import hunt as hunt_module
from . import temp
from .brom import format_report, probe as brom_probe
from .device import probe as device_probe
from .errors import LapisRootError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lapisroot",
        description=(
            "Temporary KernelSU (LKM) root for the Redmi Note 15 Pro 5G "
            "(lapis / MediaTek MT6878)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"lapisroot {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="show the connected device, kernel and KMI")
    detect.add_argument("--serial")

    plan = subparsers.add_parser("plan", help="explain what is possible right now")
    plan.add_argument("--serial")
    plan.add_argument("--stock", type=Path, help="stock init_boot.img, ROM directory or ROM archive")

    hunt = subparsers.add_parser(
        "hunt", help="match the build against known LPEs and optionally run a local PoC"
    )
    hunt.add_argument("--serial")
    hunt.add_argument("--catalog", type=Path, help="custom CVE catalog JSON")
    hunt.add_argument("--poc-dir", type=Path, help="directory containing pocs/<CVE>/")
    hunt.add_argument("--state-dir", type=Path, help="where to write the JSON report")
    hunt.add_argument("--execute", action="store_true", help="run matching local PoCs")
    hunt.add_argument("--yes", action="store_true", help="do not ask before executing")
    hunt.add_argument("--json", action="store_true", dest="json_report", help="write a JSON report")

    start = subparsers.add_parser(
        "start", help="patch init_boot with KernelSU LKM and flash it (temporary root)"
    )
    start.add_argument("--serial")
    start.add_argument("--stock", type=Path, required=True,
                       help="stock init_boot.img, extracted fastboot ROM directory, or ROM archive")
    start.add_argument("--kmi", help="KMI such as android14-6.1 (auto-detected over adb)")
    start.add_argument("--lkm", type=Path, help="custom kernelsu.ko matching the running kernel")
    start.add_argument("--ksu-version", default="latest", help="KernelSU release tag (default: latest)")
    start.add_argument("--variant", default="KernelSU", help="KernelSU or KernelSU-Next")
    start.add_argument("--allow-shell", action="store_true",
                       help="let adb shell use su without a manager prompt")
    start.add_argument("--no-manager", action="store_true", help="do not download/install the manager APK")
    start.add_argument("--state-dir", type=Path, help="state directory (default: XDG state dir)")
    start.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    start.add_argument("--dry-run", action="store_true", help="show the plan without changing anything")

    stop = subparsers.add_parser("stop", help="restore the stock init_boot and reboot")
    stop.add_argument("--state-dir", type=Path)
    stop.add_argument("--yes", action="store_true")
    stop.add_argument("--dry-run", action="store_true")

    status = subparsers.add_parser("status", help="show the device and the active session")
    status.add_argument("--serial")
    status.add_argument("--state-dir", type=Path)

    brom = subparsers.add_parser("brom", help="MediaTek BROM/preloader diagnostics (read-only)")
    brom_sub = brom.add_subparsers(dest="brom_command", required=True)
    brom_probe_parser = brom_sub.add_parser(
        "probe", help="run `mtk printgpt` and report DAA/SLA/DA-loader status"
    )
    brom_probe_parser.add_argument(
        "--mtk-cmd", nargs="+", help="mtkclient command, e.g. --mtk-cmd python3 /path/mtk.py"
    )

    subparsers.add_parser("version", help="print the lapisroot version")
    return parser


def _detect(args: argparse.Namespace) -> int:
    device = device_probe(args.serial)
    if device is None:
        print("no device detected over adb or fastboot")
        return 2
    for line in device.describe():
        print(line)
    return 0


def _start(args: argparse.Namespace) -> int:
    return temp.start(
        temp.StartOptions(
            serial=args.serial,
            stock_image=args.stock,
            state_dir=args.state_dir,
            kmi=args.kmi,
            lkm=args.lkm,
            ksu_version=args.ksu_version,
            variant=args.variant,
            allow_shell=args.allow_shell,
            no_manager=args.no_manager,
            assume_yes=args.yes,
            dry_run=args.dry_run,
        )
    )


def _stop(args: argparse.Namespace) -> int:
    return temp.stop(
        temp.StopOptions(
            state_dir=args.state_dir,
            assume_yes=args.yes,
            dry_run=args.dry_run,
        )
    )


def _brom(args: argparse.Namespace) -> int:
    report = brom_probe(mtk_cmd=args.mtk_cmd)
    for line in format_report(report):
        print(line)
    return 0


def _hunt(args: argparse.Namespace) -> int:
    return hunt_module.hunt(
        hunt_module.HuntOptions(
            serial=args.serial,
            catalog=args.catalog,
            poc_dir=args.poc_dir,
            state_dir=args.state_dir,
            execute=args.execute,
            assume_yes=args.yes,
            json_report=args.json_report,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "detect":
            return _detect(args)
        if args.command == "plan":
            return temp.plan(args)
        if args.command == "hunt":
            return _hunt(args)
        if args.command == "start":
            return _start(args)
        if args.command == "stop":
            return _stop(args)
        if args.command == "status":
            return temp.status(args)
        if args.command == "brom":
            return _brom(args)
        if args.command == "version":
            print(f"lapisroot {__version__}")
            return 0
        parser.error(f"unknown command: {args.command}")
        return 2
    except LapisRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
