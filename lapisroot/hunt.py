"""Automated LPE reconnaissance with gated PoC execution.

The catalog is a curated list of known Android/MediaTek privilege-escalation
issues.  This module never ships an exploit: it collects facts from the device,
evaluates each catalog entry against the build's security patch level, kernel
and platform, and only executes a PoC that the user has placed under
``pocs/<CVE>/`` with a manifest.  When no catalogued issue applies, it says so.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from . import adb
from .device import Mode, probe
from .errors import LapisRootError, SafetyError
from .kernelsu import detect_kmi
from .proc import Runner, run as _run
from .workspace import Workspace, utc_now


class Status(str, Enum):
    VULNERABLE = "vulnerable"
    PATCHED = "patched"
    NOT_APPLICABLE = "not-applicable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Facts:
    serial: str
    model: str | None
    codename: str | None
    platform: str | None
    android: str | None
    sdk: int | None
    build: str | None
    security_patch: str | None
    kernel_release: str | None
    kmi: str | None
    selinux: str | None
    build_type: str | None
    build_tags: str | None
    debuggable: bool | None
    abi: str | None

    def describe(self) -> list[str]:
        return [
            f"serial      : {self.serial}",
            f"device      : {self.model or '?'} [{self.codename or '?'}]",
            f"platform    : {self.platform or '?'}",
            f"android     : {self.android or '?'} (sdk {self.sdk if self.sdk is not None else '?'})",
            f"build       : {self.build or '?'}",
            f"patch level : {self.security_patch or '?'}",
            f"kernel      : {self.kernel_release or '?'}",
            f"kmi         : {self.kmi or '?'}",
            f"selinux     : {self.selinux or '?'}",
            f"build type  : {self.build_type or '?'} ({self.build_tags or '?'})",
            f"debuggable  : {self.debuggable if self.debuggable is not None else '?'}",
            f"abi         : {self.abi or '?'}",
        ]


def collect_facts(serial: str, *, runner: Runner = _run) -> Facts:
    props = adb.getprop_map(serial, runner)
    uname = adb.shell(serial, "uname", "-r", runner=runner, timeout=15.0)
    selinux = adb.shell(serial, "getenforce", runner=runner, timeout=15.0)
    sdk_text = props.get("ro.build.version.sdk", "")
    debuggable_text = props.get("ro.debuggable")
    kernel = uname.stdout.strip() or None
    return Facts(
        serial=serial,
        model=props.get("ro.product.model"),
        codename=props.get("ro.product.device"),
        platform=props.get("ro.board.platform"),
        android=props.get("ro.build.version.release"),
        sdk=int(sdk_text) if sdk_text.isdigit() else None,
        build=props.get("ro.build.display.id") or props.get("ro.build.version.incremental"),
        security_patch=props.get("ro.build.version.security_patch"),
        kernel_release=kernel,
        kmi=detect_kmi(kernel),
        selinux=selinux.stdout.strip() or None,
        build_type=props.get("ro.build.type"),
        build_tags=props.get("ro.build.tags"),
        debuggable=(debuggable_text == "1") if debuggable_text is not None else None,
        abi=props.get("ro.product.cpu.abi"),
    )


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    component: str
    impact: str = "root"
    platform: str | None = None
    fixed_security_patch: str | None = None
    max_sdk: int | None = None
    min_kernel: str | None = None
    max_kernel: str | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        try:
            entry = cls(
                id=str(data["id"]),
                title=str(data["title"]),
                component=str(data["component"]),
                impact=str(data.get("impact", "root")),
                platform=data.get("platform"),
                fixed_security_patch=data.get("fixed_security_patch"),
                max_sdk=int(data["max_sdk"]) if data.get("max_sdk") is not None else None,
                min_kernel=data.get("min_kernel"),
                max_kernel=data.get("max_kernel"),
                notes=str(data.get("notes", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LapisRootError(f"invalid catalog entry: {data!r}") from exc
        if not any(
            (
                entry.fixed_security_patch,
                entry.max_sdk is not None,
                entry.min_kernel,
                entry.max_kernel,
            )
        ):
            raise LapisRootError(f"catalog entry {entry.id} has no constraints")
        return entry


@dataclass(frozen=True)
class Catalog:
    entries: tuple[Entry, ...]
    source: Path | None = None


def default_catalog_path() -> Path:
    return Path(__file__).with_name("data") / "android_lpe_catalog.json"


def load_catalog(path: Path | None = None) -> Catalog:
    source = Path(path) if path is not None else default_catalog_path()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LapisRootError(f"cannot read catalog {source}: {exc}") from exc
    if data.get("schema") != 1:
        raise LapisRootError(f"unsupported catalog schema in {source}")
    entries = tuple(Entry.from_dict(item) for item in data.get("entries", []))
    return Catalog(entries=entries, source=source)


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _kernel(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value.strip())
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def evaluate(entry: Entry, facts: Facts) -> Status:
    if entry.platform and facts.platform:
        if entry.platform.lower() not in (facts.platform.lower(), (facts.codename or "").lower()):
            return Status.NOT_APPLICABLE

    if entry.max_sdk is not None and facts.sdk is not None and facts.sdk > entry.max_sdk:
        return Status.PATCHED

    if entry.fixed_security_patch:
        device_patch = _date(facts.security_patch)
        fixed_patch = _date(entry.fixed_security_patch)
        if device_patch is None or fixed_patch is None:
            return Status.UNKNOWN
        if device_patch >= fixed_patch:
            return Status.PATCHED

    kernel = _kernel(facts.kernel_release)
    if entry.min_kernel or entry.max_kernel:
        if kernel is None:
            return Status.UNKNOWN
        if entry.min_kernel and kernel < _kernel(entry.min_kernel):
            return Status.NOT_APPLICABLE
        if entry.max_kernel and kernel > _kernel(entry.max_kernel):
            return Status.NOT_APPLICABLE

    return Status.VULNERABLE


@dataclass(frozen=True)
class PocSpec:
    cve: str
    command: tuple[str, ...]
    timeout: float = 60.0
    reversible: bool = False
    expected: str | None = None
    cwd: str | None = None


def find_poc(entry: Entry, poc_dir: Path) -> PocSpec | None:
    directory = Path(poc_dir) / entry.id
    manifest = directory / "manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LapisRootError(f"invalid PoC manifest {manifest}: {exc}") from exc
        command = data.get("command")
        if not command and data.get("script"):
            command = ["sh", str(directory / str(data["script"]))]
        if not isinstance(command, list) or not command:
            raise LapisRootError(f"PoC manifest {manifest} needs a non-empty command list")
        return PocSpec(
            cve=entry.id,
            command=tuple(str(part) for part in command),
            timeout=float(data.get("timeout", 60)),
            reversible=bool(data.get("reversible", False)),
            expected=data.get("expected"),
            cwd=str(directory),
        )
    script = directory / "run.sh"
    if script.is_file():
        return PocSpec(cve=entry.id, command=("sh", str(script)), cwd=str(directory))
    return None


@dataclass
class HuntOptions:
    serial: str | None = None
    catalog: Path | None = None
    poc_dir: Path | None = None
    state_dir: Path | None = None
    execute: bool = False
    assume_yes: bool = False
    json_report: bool = False
    runner: Runner = _run


def _print_results(results) -> None:
    header = f"{'CVE':<18} {'status':<16} {'component':<12} {'poc':<4} title"
    print(header)
    print("-" * len(header))
    for entry, status, poc in results:
        print(
            f"{entry.id:<18} {status.value:<16} {entry.component:<12} "
            f"{('yes' if poc else 'no'):<4} {entry.title}"
        )


def hunt(options: HuntOptions) -> int:
    device = probe(options.serial, runner=options.runner)
    if device is None:
        print("no device detected over adb")
        return 2
    if device.mode is not Mode.ADB or device.adb_state != "device":
        print("adb is not authorized. Unlock the phone and accept the USB debugging prompt.")
        return 2
    if not device.is_target:
        print(f"unsupported device: {device.codename or device.model or 'unknown'}")
        return 2

    facts = collect_facts(device.serial, runner=options.runner)
    for line in facts.describe():
        print(line)
    print()

    catalog = load_catalog(options.catalog)
    poc_dir = Path(options.poc_dir) if options.poc_dir else Path.cwd() / "pocs"
    results = [
        (entry, evaluate(entry, facts), find_poc(entry, poc_dir))
        for entry in catalog.entries
    ]
    _print_results(results)
    print()

    candidates = [item for item in results if item[1] is Status.VULNERABLE]
    if not candidates:
        print("verdict: no catalogued public LPE applies to this build.")
        print(
            "The bootloader unlock + KernelSU LKM path in `lapisroot start` "
            "is the remaining route."
        )
        return 0

    print(f"verdict: {len(candidates)} candidate(s) need attention.")
    for entry, _status, _poc in candidates:
        print(f"  - {entry.id}: {entry.notes}")

    if not options.execute:
        print("not executing (pass --execute to run a local PoC).")
        return 0

    executable = [item for item in candidates if item[2] is not None]
    if not executable:
        print("no local PoC found under pocs/; nothing was executed.")
        print("Add pocs/<CVE>/manifest.json to enable execution.")
        return 0

    if not options.assume_yes:
        if not sys.stdin.isatty():
            raise SafetyError("refusing to execute PoCs non-interactively; pass --yes")
        answer = input(f"Execute {len(executable)} PoC(s)? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("aborted.")
            return 0

    report = {
        "started_at": utc_now(),
        "facts": asdict(facts),
        "results": [],
    }
    for entry, _status, poc in executable:
        print(f"running {entry.id}: {' '.join(poc.command)}")
        result = options.runner(list(poc.command), timeout=poc.timeout, cwd=poc.cwd)
        print(result.output or "(no output)")
        report["results"].append(
            {
                "id": entry.id,
                "command": list(poc.command),
                "returncode": result.returncode,
                "output": result.output,
            }
        )

    if options.json_report:
        workspace = Workspace(options.state_dir)
        workspace.ensure()
        reports = workspace.root / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().replace(":", "").replace("+", "_")
        path = reports / f"hunt-{stamp}.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"report: {path}")
    return 0
