import unittest

from lapisroot import adb, fastboot, kernelsu
from lapisroot.proc import Result


def fake(argv, *, stdout="", stderr="", code=0, **kwargs):
    return Result(tuple(argv), code, stdout, stderr)


class AdbParsingTest(unittest.TestCase):
    def test_list_devices_keeps_unauthorized(self):
        def runner(argv, **kwargs):
            return fake(
                argv,
                stdout="List of devices attached\nABC\tdevice\nDEF\tunauthorized\n\n",
            )

        self.assertEqual(
            adb.list_devices(runner),
            [("ABC", "device"), ("DEF", "unauthorized")],
        )

    def test_list_devices_ignores_daemon_chatter_and_keeps_state_text(self):
        output = (
            "adb server version (41) doesn't match this client (37); killing...\n"
            "* daemon started successfully\n"
            "List of devices attached\n"
            "SER\tdevice\n"
            "BAD\tno permissions (user in plugdev group; are your udev rules wrong?)\n"
        )

        def runner(argv, **kwargs):
            return fake(argv, stdout=output)

        self.assertEqual(
            adb.list_devices(runner),
            [
                ("SER", "device"),
                ("BAD", "no permissions (user in plugdev group; are your udev rules wrong?)"),
            ],
        )

    def test_authorized_serial_prefers_requested(self):
        def runner(argv, **kwargs):
            return fake(argv, stdout="A\tdevice\nB\tdevice\n")

        self.assertEqual(adb.authorized_serial(runner, preferred="B"), "B")
        self.assertIsNone(adb.authorized_serial(runner, preferred="C"))

    def test_getprop_map(self):
        dump = (
            "[ro.product.device]: [lapis]\n"
            "[ro.boot.flash.locked]: [0]\n"
            "[ro.boot.slot_suffix]: [_a]\n"
        )

        def runner(argv, **kwargs):
            return fake(argv, stdout=dump)

        props = adb.getprop_map("SER", runner)
        self.assertEqual(props["ro.product.device"], "lapis")
        self.assertEqual(props["ro.boot.slot_suffix"], "_a")


class FastbootParsingTest(unittest.TestCase):
    def test_list_devices(self):
        def runner(argv, **kwargs):
            return fake(argv, stdout="SER\tfastboot\n")

        self.assertEqual(fastboot.list_devices(runner), ["SER"])

    def test_getvar_reads_stderr(self):
        def runner(argv, **kwargs):
            return fake(argv, stderr="unlocked: yes\nfinished. total time: 0.001s\n")

        self.assertEqual(fastboot.getvar("SER", "unlocked", runner), "yes")

    def test_is_unlocked_from_getvar(self):
        def runner(argv, **kwargs):
            return fake(argv, stderr="unlocked: yes\n")

        self.assertIs(fastboot.is_unlocked("SER", runner), True)

    def test_is_unlocked_from_oem_device_info(self):
        def runner(argv, **kwargs):
            if list(argv)[-1] == "unlocked":
                return fake(argv, code=1)
            return fake(argv, stdout="Device unlocked: false\n")

        self.assertIs(fastboot.is_unlocked("SER", runner), False)


class KmiDetectionTest(unittest.TestCase):
    def test_gki_kernels(self):
        cases = {
            "6.1.138-android14-11-g0c3d559bcd85": "android14-6.1",
            "5.10.198-android12-9-00001-gabc": "android12-5.10",
            "5.15.153-android13-8-00002-gdef": "android13-5.15",
            "6.6.30-android15-6-g86d10b30f51f": "android15-6.6",
            "6.12.30-android16-5-gabc": "android16-6.12",
        }
        for uname, expected in cases.items():
            self.assertEqual(kernelsu.detect_kmi(uname), expected, uname)

    def test_unknown_kernels(self):
        self.assertIsNone(kernelsu.detect_kmi("4.19.191-gabc"))
        self.assertIsNone(kernelsu.detect_kmi(""))
        self.assertIsNone(kernelsu.detect_kmi(None))


if __name__ == "__main__":
    unittest.main()
