"""KernelSU LKM integration.

KernelSU's ``ksud`` patches the ramdisk that lives in ``init_boot`` on this
device: it injects ``ksuinit`` (as ``init``), keeps the stock ``init`` as
``init.real``, and drops ``kernelsu.ko`` plus ``ksu_config`` into the ramdisk.
The kernel itself is never replaced, which is why LKM is the right mode for a
MediaTek device with vendor kernel modules.
"""

from __future__ import annotations

import json
import os
import platform as _platform
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .errors import LapisRootError, PatchError
from .proc import Runner, run as _run

DEFAULT_VARIANT = "KernelSU"
DEFAULT_KMI = "android14-6.1"

#: Host-patchable variants.  SukiSU only publishes Android-targeted ksud
#: binaries, so it is intentionally absent here.
VARIANTS = {
    "kernelsu": "tiann/KernelSU",
    "kernelsu-next": "KernelSU-Next/KernelSU-Next",
    "ksunext": "KernelSU-Next/KernelSU-Next",
}

KSUD_ASSETS = {
    "x86_64": "ksud-x86_64-unknown-linux-musl",
    "amd64": "ksud-x86_64-unknown-linux-musl",
    "aarch64": "ksud-aarch64-unknown-linux-musl",
    "arm64": "ksud-aarch64-unknown-linux-musl",
}

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"

_KMI_RE = re.compile(r"^(\d+)\.(\d+)\.\d+.*?-android(\d+)-")

Opener = Callable[[str], bytes]


def _http_get(url: str, timeout: float = 180.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "lapisroot/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise PatchError(f"HTTP {exc.code} while fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise PatchError(f"cannot reach {url}: {exc.reason}") from exc


def detect_kmi(uname_release: str | None) -> str | None:
    """Turn ``6.1.138-android14-11-g...`` into ``android14-6.1``."""
    if not uname_release:
        return None
    match = _KMI_RE.match(uname_release.strip())
    if match is None:
        return None
    major, minor, android = match.groups()
    return f"android{android}-{major}.{minor}"


def host_ksud_asset(machine: str | None = None, system: str | None = None) -> str:
    system = (system or _platform.system()).lower()
    if system != "linux":
        raise PatchError(
            "host-side patching requires Linux. On Windows/macOS, use the "
            "KernelSU Manager app on the phone instead."
        )
    machine = (machine or _platform.machine()).lower()
    name = KSUD_ASSETS.get(machine)
    if name is None:
        raise PatchError(f"no ksud build for host architecture '{machine}'")
    return name


@dataclass(frozen=True)
class Release:
    tag: str
    assets: dict[str, str]


@dataclass(frozen=True)
class KsuBundle:
    version: str
    ksud: Path
    manager_apk: Path | None = None
    manager_error: str | None = None
    assets: dict[str, str] = field(default_factory=dict)


def resolve_release(
    version: str = "latest",
    *,
    variant: str = DEFAULT_VARIANT,
    opener: Opener = _http_get,
) -> Release:
    repo = VARIANTS.get(variant.lower())
    if repo is None:
        raise PatchError(
            f"unsupported KernelSU variant '{variant}'. "
            f"Host patching supports: {', '.join(sorted(VARIANTS))}"
        )
    if version == "latest":
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        tag = version if version.startswith("v") else f"v{version}"
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"

    try:
        data = json.loads(opener(url).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PatchError(f"invalid release metadata from {url}") from exc

    assets = {
        asset["name"]: asset["browser_download_url"]
        for asset in data.get("assets", [])
        if "name" in asset and "browser_download_url" in asset
    }
    return Release(tag=data.get("tag_name", version), assets=assets)


def pick_manager_asset(assets: dict[str, str]) -> str | None:
    candidates = [name for name in assets if name.lower().endswith("-release.apk")]
    if not candidates:
        return None
    preferred = [name for name in candidates if "spoofed" not in name.lower()]
    return sorted(preferred or candidates)[0]


def prepare(
    version: str = "latest",
    *,
    state_dir: Path,
    variant: str = DEFAULT_VARIANT,
    fetch_manager: bool = True,
    opener: Opener = _http_get,
    runner: Runner = _run,
) -> KsuBundle:
    """Resolve a release, download ``ksud`` and (optionally) the manager APK."""
    cache = Path(state_dir) / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    release = resolve_release(version, variant=variant, opener=opener)
    ksud_name = host_ksud_asset()
    ksud_url = release.assets.get(ksud_name)
    if ksud_url is None:
        raise PatchError(f"release {release.tag} has no asset named {ksud_name}")

    ksud_path = cache / f"ksud-{release.tag}-{ksud_name}"
    if not ksud_path.exists():
        ksud_path.write_bytes(opener(ksud_url))
        os.chmod(ksud_path, 0o755)

    probe = runner([str(ksud_path), "--version"], timeout=20.0)
    if probe.returncode != 0 or "ksud" not in probe.output.lower():
        raise PatchError(
            f"downloaded ksud at {ksud_path} does not run on this host:\n{probe.output}"
        )

    manager_apk: Path | None = None
    manager_error: str | None = None
    if fetch_manager:
        name = pick_manager_asset(release.assets)
        if name is None:
            manager_error = f"release {release.tag} has no manager APK asset"
        else:
            manager_apk = cache / name
            if not manager_apk.exists():
                try:
                    manager_apk.write_bytes(opener(release.assets[name]))
                except LapisRootError as exc:
                    manager_apk = None
                    manager_error = str(exc)

    return KsuBundle(
        version=release.tag,
        ksud=ksud_path,
        manager_apk=manager_apk,
        manager_error=manager_error,
        assets=dict(release.assets),
    )


def _check_boot_magic(path: Path) -> None:
    with Path(path).open("rb") as handle:
        magic = handle.read(8)
    if magic not in (BOOT_MAGIC, VENDOR_BOOT_MAGIC):
        raise PatchError(
            f"{path} is not a valid Android boot image after patching "
            f"(magic={magic!r})"
        )


def patch(
    bundle: KsuBundle,
    init_boot: Path,
    out_dir: Path,
    *,
    kmi: str,
    lkm: Path | None = None,
    allow_shell: bool = False,
    runner: Runner = _run,
) -> Path:
    """Patch ``init_boot`` with KernelSU LKM and return the patched image."""
    init_boot = Path(init_boot).expanduser().resolve()
    if not init_boot.is_file():
        raise PatchError(f"init_boot image does not exist: {init_boot}")
    if not kmi:
        raise PatchError("a KMI is required, for example --kmi android14-6.1")

    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{init_boot.stem}-kernelsu.img"

    args = [
        str(bundle.ksud),
        "boot-patch",
        "-b",
        str(init_boot),
        "--kmi",
        kmi,
        "--out",
        str(out_dir),
        "--out-name",
        out_name,
    ]
    if lkm is not None:
        args += ["-m", str(Path(lkm).expanduser().resolve())]
    if allow_shell:
        args += ["--allow-shell"]

    result = runner(args, timeout=300.0)
    if result.returncode != 0:
        raise PatchError(f"ksud boot-patch failed:\n{result.output}")

    produced = out_dir / out_name
    if not produced.is_file():
        images = sorted(
            out_dir.glob("*.img"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not images:
            raise PatchError(
                "ksud reported success but produced no image:\n" + result.output
            )
        produced = images[0]

    _check_boot_magic(produced)
    return produced


def install_manager(serial: str, apk: Path, *, runner: Runner = _run):
    """Install the KernelSU manager APK over adb (best effort)."""
    return runner(
        ["adb", "-s", serial, "install", "-r", str(apk)],
        timeout=180.0,
    )


def check_root(serial: str, *, runner: Runner = _run, timeout: float = 20.0) -> bool | None:
    """Return True when ``su -c id`` reports uid=0, None when undecidable."""
    try:
        result = runner(
            ["adb", "-s", serial, "shell", "su", "-c", "id"],
            timeout=timeout,
        )
    except LapisRootError:
        return None
    if result.returncode == 0 and "uid=0" in result.stdout:
        return True
    return False
