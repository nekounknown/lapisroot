"""Read-only MediaTek BROM/preloader diagnostics.

MT6878 support in mtkclient is still incomplete, and Xiaomi's preloader may
enforce DAA/SLA.  This module never writes flash: it runs ``mtk printgpt`` and
reports what the preloader says, so the user can decide whether the BROM route
is even worth pursuing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import CommandNotFound, CommandTimeout
from .proc import Runner, run as _run, which

MTK_CANDIDATES = ("mtk", "mtk.py", "mtkclient")


@dataclass
class BromReport:
    cpu: str | None = None
    sbc: bool | None = None
    sla: bool | None = None
    daa: bool | None = None
    unprotected: bool | None = None
    da_loader_missing: bool = False
    daa_verify_failed: bool = False
    raw: str = ""

    @property
    def write_possible(self) -> bool:
        return (
            self.unprotected is True
            and self.daa is not True
            and not self.da_loader_missing
            and not self.daa_verify_failed
        )


def find_mtkclient() -> list[str] | None:
    for candidate in MTK_CANDIDATES:
        path = which(candidate)
        if path is not None:
            return [path]
    return None


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None


def _flag(text: str, name: str) -> bool | None:
    match = re.search(rf"{re.escape(name)}\s*:\s*(True|False)", text, re.IGNORECASE)
    return _bool(match.group(1)) if match else None


def parse_report(text: str) -> BromReport:
    cpu_match = re.search(r"CPU:\s*(.+)", text)
    report = BromReport(
        cpu=cpu_match.group(1).strip() if cpu_match else None,
        sbc=_flag(text, "SBC enabled"),
        sla=_flag(text, "SLA enabled"),
        daa=_flag(text, "DAA enabled"),
        da_loader_missing="No valid da loader found" in text,
        daa_verify_failed="DAA_SIG_VERIFY_FAILED" in text,
        raw=text,
    )
    if "Device is unprotected" in text:
        report.unprotected = True
    elif "Device is still protected" in text:
        report.unprotected = False
    return report


def probe(
    *,
    mtk_cmd: list[str] | None = None,
    runner: Runner = _run,
    timeout: float = 60.0,
) -> BromReport:
    command = list(mtk_cmd) if mtk_cmd else find_mtkclient()
    if not command:
        raise CommandNotFound(
            "mtkclient was not found. Install it first "
            "(https://github.com/bkerler/mtkclient) or pass --mtk-cmd."
        )
    try:
        result = runner([*command, "printgpt"], timeout=timeout)
    except CommandTimeout as exc:
        raise CommandTimeout(
            "mtkclient did not find a device in preloader/BROM mode within "
            f"{timeout:g}s. Power the phone off, then hold Volume Up (or Volume "
            "Down) while connecting USB, and retry."
        ) from exc
    report = parse_report(result.output)
    report.raw = result.output
    return report


def format_report(report: BromReport) -> list[str]:
    def tri(value: bool | None) -> str:
        return {True: "yes", False: "no", None: "unknown"}[value]

    lines = [
        f"cpu              : {report.cpu or 'unknown'}",
        f"unprotected      : {tri(report.unprotected)}",
        f"SBC enabled      : {tri(report.sbc)}",
        f"SLA enabled      : {tri(report.sla)}",
        f"DAA enabled      : {tri(report.daa)}",
        f"DA loader missing: {tri(report.da_loader_missing)}",
        f"DAA verify failed: {tri(report.daa_verify_failed)}",
        "",
    ]
    if report.write_possible:
        lines.append(
            "result: the preloader looks writable. MT6878 is still experimental "
            "in mtkclient; do not write boot partitions on a locked bootloader."
        )
    elif report.daa_verify_failed:
        lines.append(
            "result: the preloader rejected the DA signature (DAA_SIG_VERIFY_FAILED). "
            "The BROM route is blocked on this firmware."
        )
    elif report.da_loader_missing:
        lines.append(
            "result: no DA loader matched this chip. MT6878 DA support is incomplete; "
            "the BROM route is not usable yet."
        )
    elif report.unprotected is False:
        lines.append(
            "result: the preloader is protected. The BROM route is blocked unless a "
            "BROM exploit for this chip and firmware exists."
        )
    else:
        lines.append(
            "result: no device was detected in preloader/BROM mode, or the output "
            "did not contain a protection status."
        )
    return lines
