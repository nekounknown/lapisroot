import unittest

from lapisroot import device as device_module
from lapisroot.device import Mode, probe
from lapisroot.proc import Result

PROPS = (
    "[ro.product.device]: [lapis]\n"
    "[ro.product.model]: [REDMI Note 15 Pro 5G]\n"
    "[ro.board.platform]: [mt6878]\n"
    "[ro.build.version.release]: [16]\n"
    "[ro.build.display.id]: [OS3.0.309.0.WPPMIXM]\n"
    "[ro.boot.slot_suffix]: [_a]\n"
    "[ro.boot.flash.locked]: [0]\n"
)


def adb_runner(argv, **kwargs):
    argv = list(argv)
    if argv[:2] == ["adb", "devices"]:
        return Result(tuple(argv), 0, "List of devices attached\nSER\tdevice\n", "")
    if argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "getprop":
        return Result(tuple(argv), 0, PROPS, "")
    if argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "uname":
        return Result(tuple(argv), 0, "6.1.138-android14-11-gabc\n", "")
    return Result(tuple(argv), 0, "", "")


class AdbProbeTest(unittest.TestCase):
    def test_probe_reads_identity_and_kmi(self):
        device = probe(runner=adb_runner)
        self.assertIsNotNone(device)
        self.assertEqual(device.mode, Mode.ADB)
        self.assertEqual(device.codename, "lapis")
        self.assertEqual(device.platform, "mt6878")
        self.assertEqual(device.slot, "a")
        self.assertIs(device.bootloader_locked, False)
        self.assertEqual(device.kmi, "android14-6.1")
        self.assertTrue(device.is_target)

    def test_probe_marks_unauthorized(self):
        def runner(argv, **kwargs):
            argv = list(argv)
            if argv[:2] == ["adb", "devices"]:
                return Result(tuple(argv), 0, "SER\tunauthorized\n", "")
            return Result(tuple(argv), 0, "", "")

        device = probe(runner=runner)
        self.assertIsNotNone(device)
        self.assertEqual(device.adb_state, "unauthorized")
        self.assertIsNone(device.codename)


class FastbootProbeTest(unittest.TestCase):
    def test_probe_in_fastboot(self):
        values = {
            "product": "lapis",
            "current-slot": "b",
            "version": "0.4",
            "build": "OS3.0.309.0.WPPMIXM",
            "unlocked": "yes",
        }

        def runner(argv, **kwargs):
            argv = list(argv)
            if argv[:2] == ["fastboot", "devices"]:
                return Result(tuple(argv), 0, "SER\tfastboot\n", "")
            if argv[:2] == ["fastboot", "-s"]:
                name = argv[-1]
                if name in values:
                    return Result(tuple(argv), 0, "", f"{name}: {values[name]}\n")
            return Result(tuple(argv), 0, "", "")

        device = probe(runner=runner)
        self.assertIsNotNone(device)
        self.assertEqual(device.mode, Mode.FASTBOOT)
        self.assertEqual(device.codename, "lapis")
        self.assertEqual(device.slot, "b")
        self.assertIs(device.bootloader_locked, False)
        self.assertIsNone(device.kmi)

    def test_no_device(self):
        def runner(argv, **kwargs):
            return Result(tuple(argv), 0, "", "")

        self.assertIsNone(probe(runner=runner))


if __name__ == "__main__":
    unittest.main()
