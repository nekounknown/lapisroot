import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from lapisroot import firmware
from lapisroot.errors import StockImageError


def make_image(path: Path, size: int = 2 * 1024 * 1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ANDROID!" + b"\0" * (size - 8))
    return path


class FindTest(unittest.TestCase):
    def test_find_in_rom_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = make_image(root / "images" / "init_boot.img")
            self.assertEqual(firmware.find_in_directory(root), image)

    def test_materialize_accepts_file_and_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = make_image(root / "images" / "init_boot.img")
            work = root / "work"
            self.assertEqual(firmware.materialize(image, work), image)
            self.assertEqual(firmware.materialize(root, work), image)

    def test_materialize_extracts_single_member_from_tar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = make_image(root / "source" / "init_boot.img")
            archive = root / "rom.tgz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(image, arcname="rom/images/init_boot.img")
            extracted = firmware.materialize(archive, root / "work")
            self.assertTrue(extracted.is_file())
            self.assertEqual(extracted.read_bytes()[:8], b"ANDROID!")

    def test_materialize_extracts_single_member_from_zip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = make_image(root / "source" / "init_boot.img")
            archive = root / "rom.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(image, arcname="rom/images/init_boot.img")
            extracted = firmware.materialize(archive, root / "work")
            self.assertTrue(extracted.is_file())
            self.assertEqual(extracted.read_bytes()[:8], b"ANDROID!")

    def test_missing_image_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(StockImageError):
                firmware.materialize(Path(temp), Path(temp) / "work")


class ValidateTest(unittest.TestCase):
    def test_valid_image_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            image = make_image(Path(temp) / "init_boot.img")
            firmware.validate_boot_image(image)

    def test_small_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "init_boot.img"
            image.write_bytes(b"ANDROID!" + b"\0" * 100)
            with self.assertRaises(StockImageError):
                firmware.validate_boot_image(image)

    def test_bad_magic_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "init_boot.img"
            image.write_bytes(b"NOTABOOT" + b"\0" * (2 * 1024 * 1024))
            with self.assertRaises(StockImageError):
                firmware.validate_boot_image(image)


if __name__ == "__main__":
    unittest.main()
