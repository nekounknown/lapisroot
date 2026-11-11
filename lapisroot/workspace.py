"""Persistent session state.

The journal is what makes root *temporary*: it records the exact stock image
that was replaced, so ``lapisroot stop`` can put it back byte-for-byte.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import BOOT_PARTITION
from .errors import StockImageError

SCHEMA = 1


def default_state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base).expanduser() / "lapisroot"
    return Path.home() / ".local" / "state" / "lapisroot"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Journal:
    serial: str
    codename: str
    stock_image: str
    stock_sha256: str
    patched_sha256: str
    root_version: str
    started_at: str
    variant: str | None = None
    boot_partition: str = BOOT_PARTITION
    build: str | None = None
    slot: str | None = None
    schema: int = SCHEMA
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Journal":
        known = {
            "serial",
            "codename",
            "stock_image",
            "stock_sha256",
            "patched_sha256",
            "root_version",
            "started_at",
            "variant",
            "boot_partition",
            "build",
            "slot",
            "schema",
            "extra",
        }
        filtered = {key: value for key, value in data.items() if key in known}
        return cls(**filtered)


class Workspace:
    """State directory: journal, stock-image backups and the Magisk cache."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root).expanduser() if root else default_state_dir()

    @property
    def journal_path(self) -> Path:
        return self.root / "journal.json"

    @property
    def images_dir(self) -> Path:
        return self.root / "images"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def ensure(self) -> None:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- journal ---------------------------------------------------------
    def save_journal(self, journal: Journal) -> Path:
        self.ensure()
        temporary = self.journal_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(journal.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.journal_path)
        return self.journal_path

    def load_journal(self) -> Journal | None:
        if not self.journal_path.exists():
            return None
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StockImageError(f"cannot read journal {self.journal_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise StockImageError(f"journal {self.journal_path} is not an object")
        return Journal.from_dict(data)

    def clear_journal(self) -> None:
        try:
            self.journal_path.unlink()
        except FileNotFoundError:
            pass

    # -- stock image -----------------------------------------------------
    def store_stock(self, source: Path) -> tuple[Path, str]:
        """Copy ``source`` into the workspace and return ``(path, sha256)``."""
        self.ensure()
        digest = sha256_file(source)
        destination = self.images_dir / f"stock-{BOOT_PARTITION}-{digest[:12]}.img"
        if not destination.exists():
            destination.write_bytes(source.read_bytes())
        if sha256_file(destination) != digest:
            raise StockImageError(f"backup copy of {source} is corrupt")
        return destination, digest

    def stock_from_journal(self, journal: Journal) -> Path:
        path = Path(journal.stock_image)
        if not path.exists():
            raise StockImageError(
                f"the stock image recorded in the journal is missing: {path}"
            )
        if sha256_file(path) != journal.stock_sha256:
            raise StockImageError(
                f"the stock image {path} no longer matches the recorded sha256"
            )
        return path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
