import json
import tempfile
import unittest
from pathlib import Path

from lapisroot import kernelsu
from lapisroot.errors import PatchError
from lapisroot.proc import Result


class AssetTest(unittest.TestCase):
    def test_host_ksud_asset(self):
        self.assertEqual(
            kernelsu.host_ksud_asset("x86_64", "Linux"),
            "ksud-x86_64-unknown-linux-musl",
        )
        self.assertEqual(
            kernelsu.host_ksud_asset("aarch64", "Linux"),
            "ksud-aarch64-unknown-linux-musl",
        )
        with self.assertRaises(PatchError):
            kernelsu.host_ksud_asset("x86_64", "Darwin")

    def test_pick_manager_asset_skips_spoofed(self):
        assets = {
            "KernelSU_v1_spoofed-release.apk": "a",
            "KernelSU_v1-release.apk": "b",
            "ksud-x86_64-unknown-linux-musl": "c",
        }
        self.assertEqual(kernelsu.pick_manager_asset(assets), "KernelSU_v1-release.apk")


class ReleaseTest(unittest.TestCase):
    def test_resolve_release(self):
        payload = {
            "tag_name": "v3.3.1",
            "assets": [
                {
                    "name": "ksud-x86_64-unknown-linux-musl",
                    "browser_download_url": "http://example/ksud",
                }
            ],
        }

        def opener(url):
            return json.dumps(payload).encode()

        release = kernelsu.resolve_release("latest", opener=opener)
        self.assertEqual(release.tag, "v3.3.1")
        self.assertIn("ksud-x86_64-unknown-linux-musl", release.assets)

    def test_prepare_downloads_and_verifies(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {
                "tag_name": "v3.3.1",
                "assets": [
                    {
                        "name": "ksud-x86_64-unknown-linux-musl",
                        "browser_download_url": "http://example/ksud",
                    },
                    {
                        "name": "KernelSU_v3.3.1_1-release.apk",
                        "browser_download_url": "http://example/manager.apk",
                    },
                ],
            }

            def opener(url):
                if "api.github.com" in url:
                    return json.dumps(payload).encode()
                if url.endswith("/ksud"):
                    return b"ksud-binary"
                return b"apk-binary"

            def runner(argv, **kwargs):
                return Result(tuple(argv), 0, "ksud 3.3.1\n", "")

            bundle = kernelsu.prepare(
                "latest", state_dir=Path(temp), opener=opener, runner=runner
            )
            self.assertTrue(bundle.ksud.is_file())
            self.assertEqual(bundle.ksud.read_bytes(), b"ksud-binary")
            self.assertIsNotNone(bundle.manager_apk)
            self.assertTrue(bundle.manager_apk.is_file())


class PatchTest(unittest.TestCase):
    def _bundle(self, root: Path) -> kernelsu.KsuBundle:
        ksud = root / "ksud"
        ksud.write_text("#!/bin/sh\n", encoding="utf-8")
        return kernelsu.KsuBundle(version="v3.3.1", ksud=ksud)

    def test_patch_invokes_ksud_and_returns_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_boot = root / "init_boot.img"
            init_boot.write_bytes(b"ANDROID!" + b"\0" * (2 * 1024 * 1024))
            calls = []

            def runner(argv, **kwargs):
                argv = list(argv)
                calls.append(argv)
                out = Path(argv[argv.index("--out") + 1]) / argv[argv.index("--out-name") + 1]
                out.write_bytes(b"ANDROID!" + b"\0" * (3 * 1024 * 1024))
                return Result(tuple(argv), 0, "- Done!\n", "")

            patched = kernelsu.patch(
                self._bundle(root),
                init_boot,
                root / "out",
                kmi="android14-6.1",
                allow_shell=True,
                runner=runner,
            )
            self.assertTrue(patched.is_file())
            self.assertIn("--kmi", calls[0])
            self.assertIn("android14-6.1", calls[0])
            self.assertIn("--allow-shell", calls[0])

    def test_patch_failure_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_boot = root / "init_boot.img"
            init_boot.write_bytes(b"ANDROID!" + b"\0" * (2 * 1024 * 1024))

            def runner(argv, **kwargs):
                return Result(tuple(argv), 1, "", "invalid boot image")

            with self.assertRaises(PatchError):
                kernelsu.patch(
                    self._bundle(root), init_boot, root / "out",
                    kmi="android14-6.1", runner=runner,
                )


if __name__ == "__main__":
    unittest.main()
