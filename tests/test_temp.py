import tempfile
import unittest
from pathlib import Path

from lapisroot import kernelsu, temp
from lapisroot.proc import Result
from lapisroot.workspace import Workspace

PROPS = (
    "[ro.product.device]: [lapis]\n"
    "[ro.product.model]: [REDMI Note 15 Pro 5G]\n"
    "[ro.board.platform]: [mt6878]\n"
    "[ro.build.version.release]: [16]\n"
    "[ro.build.display.id]: [OS3.0.309.0.WPPMIXM]\n"
    "[ro.boot.slot_suffix]: [_a]\n"
    "[ro.boot.flash.locked]: [0]\n"
)

PATCHED = b"ANDROID!" + b"\0" * (3 * 1024 * 1024)


def make_runner(state: dict):
    def runner(argv, **kwargs):
        argv = list(argv)
        if argv[:2] == ["adb", "devices"]:
            return Result(tuple(argv), 0, "List of devices attached\nSER\tdevice\n", "")
        if argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "getprop":
            return Result(tuple(argv), 0, PROPS, "")
        if argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "uname":
            return Result(tuple(argv), 0, "6.1.138-android14-11-gabc\n", "")
        if len(argv) > 3 and argv[:3] == ["adb", "-s", "SER"] and argv[3] == "reboot":
            return Result(tuple(argv), 0, "", "")
        if len(argv) > 4 and argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "su":
            return Result(tuple(argv), 0, "uid=0(root) gid=0(root)\n", "")
        if argv[:2] == ["fastboot", "devices"]:
            return Result(tuple(argv), 0, "SER\tfastboot\n", "")
        if argv[:2] == ["fastboot", "-s"]:
            if argv[-1] == "current-slot":
                return Result(tuple(argv), 0, "", "current-slot: a\n")
            if argv[-1] == "unlocked":
                return Result(tuple(argv), 0, "", "unlocked: yes\n")
            if "flash" in argv:
                state.setdefault("flashes", []).append(argv)
                return Result(tuple(argv), 0, "Sending OKAY\n", "")
            if "reboot" in argv:
                return Result(tuple(argv), 0, "", "")
        if "boot-patch" in argv:
            out = Path(argv[argv.index("--out") + 1]) / argv[argv.index("--out-name") + 1]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(PATCHED)
            return Result(tuple(argv), 0, "- Done!\n", "")
        return Result(tuple(argv), 0, "", "")

    return runner


class StartStopTest(unittest.TestCase):
    def test_start_then_stop_restores_stock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stock = root / "init_boot.img"
            stock.write_bytes(b"ANDROID!" + b"\0" * (2 * 1024 * 1024))
            state: dict = {}
            runner = make_runner(state)

            original_prepare = kernelsu.prepare
            kernelsu.prepare = lambda *args, **kwargs: kernelsu.KsuBundle(
                version="vtest", ksud=root / "ksud"
            )
            try:
                rc = temp.start(
                    temp.StartOptions(
                        stock_image=stock,
                        state_dir=root / "state",
                        assume_yes=True,
                        runner=runner,
                    )
                )
            finally:
                kernelsu.prepare = original_prepare

            self.assertEqual(rc, 0)
            workspace = Workspace(root / "state")
            journal = workspace.load_journal()
            self.assertIsNotNone(journal)
            self.assertEqual(journal.serial, "SER")
            self.assertEqual(journal.slot, "a")
            self.assertEqual(journal.root_version, "vtest")
            self.assertTrue(Path(journal.stock_image).is_file())

            start_flash = state["flashes"][0]
            self.assertEqual(start_flash[3], "flash")
            self.assertEqual(start_flash[4], "init_boot")
            self.assertTrue(start_flash[5].endswith("init_boot-kernelsu.img"))

            rc = temp.stop(
                temp.StopOptions(
                    state_dir=root / "state",
                    assume_yes=True,
                    runner=runner,
                )
            )
            self.assertEqual(rc, 0)
            self.assertIsNone(workspace.load_journal())
            stop_flash = state["flashes"][-1]
            self.assertEqual(stop_flash[4], "init_boot")
            self.assertEqual(stop_flash[5], journal.stock_image)


if __name__ == "__main__":
    unittest.main()
