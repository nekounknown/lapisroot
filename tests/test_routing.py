import unittest
from pathlib import Path

from lapisroot.device import Device, Mode, Route, assess


def device(**overrides) -> Device:
    base = dict(serial="SER", mode=Mode.ADB, codename="lapis", platform="mt6878",
                bootloader_locked=False)
    base.update(overrides)
    return Device(**base)


class AssessTest(unittest.TestCase):
    def test_no_device(self):
        self.assertIs(assess(None, None).route, Route.NO_DEVICE)

    def test_unauthorized(self):
        result = assess(device(adb_state="unauthorized", codename=None), None)
        self.assertIs(result.route, Route.UNAUTHORIZED)

    def test_no_permissions(self):
        result = assess(
            device(
                adb_state="no permissions (user in plugdev group; are your udev rules wrong?)",
                codename=None,
            ),
            None,
        )
        self.assertIs(result.route, Route.UNAUTHORIZED)

    def test_unsupported(self):
        result = assess(device(codename="amethyst", platform="sm7635"), None)
        self.assertIs(result.route, Route.UNSUPPORTED)

    def test_locked(self):
        result = assess(device(bootloader_locked=True), Path("init_boot.img"))
        self.assertIs(result.route, Route.LOCKED)

    def test_unknown_lock_is_treated_as_locked(self):
        result = assess(device(bootloader_locked=None), Path("init_boot.img"))
        self.assertIs(result.route, Route.LOCKED)

    def test_needs_stock(self):
        self.assertIs(assess(device(), None).route, Route.NEEDS_STOCK)

    def test_ready(self):
        result = assess(device(), Path("init_boot.img"))
        self.assertIs(result.route, Route.READY)


if __name__ == "__main__":
    unittest.main()
