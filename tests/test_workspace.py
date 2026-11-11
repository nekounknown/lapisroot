import json
import tempfile
import unittest
from pathlib import Path

from lapisroot.errors import StockImageError
from lapisroot.workspace import Journal, Workspace, sha256_file


def make_image(path: Path, size: int = 2 * 1024 * 1024) -> Path:
    path.write_bytes(b"ANDROID!" + b"\0" * (size - 8))
    return path


class WorkspaceTest(unittest.TestCase):
    def test_store_stock_copies_and_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_image(root / "init_boot.img")
            workspace = Workspace(root / "state")
            stored, digest = workspace.store_stock(source)
            self.assertTrue(stored.is_file())
            self.assertEqual(digest, sha256_file(source))
            self.assertEqual(sha256_file(stored), digest)

    def test_journal_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp))
            journal = Journal(
                serial="SER",
                codename="lapis",
                stock_image="/tmp/stock.img",
                stock_sha256="a" * 64,
                patched_sha256="b" * 64,
                root_version="v3.3.1",
                variant="KernelSU",
                started_at="2026-01-01T00:00:00+00:00",
                build="OS3.0.309.0.WPPMIXM",
                slot="a",
            )
            workspace.save_journal(journal)
            loaded = workspace.load_journal()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.serial, "SER")
            self.assertEqual(loaded.root_version, "v3.3.1")
            self.assertEqual(loaded.variant, "KernelSU")
            workspace.clear_journal()
            self.assertIsNone(workspace.load_journal())

    def test_corrupt_journal_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp))
            workspace.ensure()
            workspace.journal_path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(StockImageError):
                workspace.load_journal()

    def test_stock_from_journal_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_image(root / "init_boot.img")
            workspace = Workspace(root / "state")
            stored, digest = workspace.store_stock(source)
            journal = Journal(
                serial="SER",
                codename="lapis",
                stock_image=str(stored),
                stock_sha256=digest,
                patched_sha256="b" * 64,
                root_version="v3.3.1",
                started_at="2026-01-01T00:00:00+00:00",
            )
            self.assertEqual(workspace.stock_from_journal(journal), stored)
            stored.write_bytes(b"tampered")
            with self.assertRaises(StockImageError):
                workspace.stock_from_journal(journal)


if __name__ == "__main__":
    unittest.main()
