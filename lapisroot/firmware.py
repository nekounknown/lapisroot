"""Locating and validating the stock ``init_boot`` image.

Xiaomi ships fastboot ROMs as multi-gigabyte ``.tgz`` archives.  We never
extract the whole thing; only the single ``init_boot.img`` member is pulled
out, which keeps disk use to a few megabytes.
"""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path

from . import BOOT_PARTITION
from .errors import StockImageError

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"

#: Archive suffixes we know how to read a single member from.
ARCHIVE_SUFFIXES = (".tgz", ".tar.gz", ".tar", ".zip")


def _is_archive(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _member_matches(name: str, partition: str) -> bool:
    base = name.rsplit("/", 1)[-1].lower()
    return base in (f"{partition}.img", f"{partition}_a.img", f"{partition}_b.img")


def _extract_member(archive: Path, destination: Path, partition: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if archive.name.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            members = [info for info in bundle.infolist() if _member_matches(info.filename, partition)]
            if not members:
                raise StockImageError(f"{archive} does not contain {partition}.img")
            member = _prefer_images_member(members)
            with bundle.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    else:
        with tarfile.open(archive, "r:*") as bundle:
            members = [info for info in bundle.getmembers() if _member_matches(info.name, partition)]
            if not members:
                raise StockImageError(f"{archive} does not contain {partition}.img")
            member = _prefer_images_member(members)
            source = bundle.extractfile(member)
            if source is None:
                raise StockImageError(f"cannot read {member.name} from {archive}")
            with source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    return destination


def _prefer_images_member(members: list) -> object:
    """Prefer ``.../images/init_boot.img`` over slot-suffixed copies."""
    def key(member: object) -> tuple[int, int]:
        name = getattr(member, "filename", None) or getattr(member, "name", "")
        lowered = name.lower()
        in_images = 1 if "/images/" in f"/{lowered}" else 0
        unsuffixed = 1 if lowered.rsplit("/", 1)[-1] == f"{BOOT_PARTITION}.img" else 0
        return (in_images, unsuffixed)

    return sorted(members, key=key)[-1]


def materialize(path: Path, workdir: Path, partition: str = BOOT_PARTITION) -> Path:
    """Return a real ``init_boot.img`` for ``path``.

    ``path`` may be the image itself, an extracted ROM directory, or a
    ``.tgz``/``.zip`` ROM archive.
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise StockImageError(f"stock image path does not exist: {path}")

    if path.is_file():
        if _is_archive(path):
            destination = workdir / f"{partition}.img"
            return _extract_member(path, destination, partition)
        return path

    found = find_in_directory(path, partition)
    if found is None:
        raise StockImageError(
            f"no {partition}.img found under {path}; point --stock at the image, "
            f"the extracted fastboot ROM directory, or the ROM archive"
        )
    return found


def find_in_directory(directory: Path, partition: str = BOOT_PARTITION) -> Path | None:
    candidates = [
        directory / f"{partition}.img",
        directory / "images" / f"{partition}.img",
        directory / f"{partition}_a.img",
        directory / "images" / f"{partition}_a.img",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    for candidate in sorted(directory.rglob(f"{partition}.img")):
        if candidate.is_file():
            return candidate
    for candidate in sorted(directory.rglob(f"{partition}_a.img")):
        if candidate.is_file():
            return candidate
    return None


def validate_boot_image(path: Path, partition: str = BOOT_PARTITION) -> None:
    """Reject files that are clearly not an Android boot/init_boot image."""
    path = Path(path)
    if not path.is_file():
        raise StockImageError(f"not a file: {path}")
    size = path.stat().st_size
    if size < 1024 * 1024:
        raise StockImageError(
            f"{path} is only {size} bytes; an {partition}.img should be several MB"
        )
    with path.open("rb") as handle:
        magic = handle.read(8)
    if magic not in (BOOT_MAGIC, VENDOR_BOOT_MAGIC):
        raise StockImageError(
            f"{path} does not look like an Android boot image "
            f"(magic={magic!r}, expected {BOOT_MAGIC!r})"
        )
