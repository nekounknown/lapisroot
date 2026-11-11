import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from lapisroot import hunt
from lapisroot.errors import LapisRootError
from lapisroot.proc import Result

PROPS = (
    "[ro.product.model]: [REDMI Note 15 Pro 5G]\n"
    "[ro.product.device]: [lapis]\n"
    "[ro.board.platform]: [mt6878]\n"
    "[ro.build.version.release]: [16]\n"
    "[ro.build.version.sdk]: [36]\n"
    "[ro.build.display.id]: [OS3.0.309.0.WPPMIXM]\n"
    "[ro.build.version.security_patch]: [2026-09-01]\n"
    "[ro.build.type]: [user]\n"
    "[ro.build.tags]: [release-keys]\n"
    "[ro.debuggable]: [0]\n"
    "[ro.product.cpu.abi]: [arm64-v8a]\n"
)


def facts(**overrides):
    base = dict(
        serial="SER",
        model="REDMI Note 15 Pro 5G",
        codename="lapis",
        platform="mt6878",
        android="16",
        sdk=36,
        build="OS3.0.309.0.WPPMIXM",
        security_patch="2026-09-01",
        kernel_release="6.1.138-android14-11-gabc",
        kmi="android14-6.1",
        selinux="Enforcing",
        build_type="user",
        build_tags="release-keys",
        debuggable=False,
        abi="arm64-v8a",
    )
    base.update(overrides)
    return hunt.Facts(**base)


def make_runner():
    def runner(argv, **kwargs):
        argv = list(argv)
        if argv[:2] == ["adb", "devices"]:
            return Result(tuple(argv), 0, "List of devices attached\nSER\tdevice\n", "")
        if argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "getprop":
            return Result(tuple(argv), 0, PROPS, "")
        if argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "uname":
            return Result(tuple(argv), 0, "6.1.138-android14-11-gabc\n", "")
        if argv[:4] == ["adb", "-s", "SER", "shell"] and argv[4] == "getenforce":
            return Result(tuple(argv), 0, "Enforcing\n", "")
        if argv == ["./poc"]:
            return Result(tuple(argv), 0, "uid=0(root) gid=0(root)\n", "")
        return Result(tuple(argv), 0, "", "")

    return runner


class EvaluateTest(unittest.TestCase):
    def test_patched_by_security_patch(self):
        entry = hunt.Entry(
            id="CVE-X", title="t", component="kernel", fixed_security_patch="2026-01-01"
        )
        self.assertIs(hunt.evaluate(entry, facts()), hunt.Status.PATCHED)

    def test_vulnerable_when_patch_is_older(self):
        entry = hunt.Entry(
            id="CVE-X", title="t", component="kernel", fixed_security_patch="2027-01-01"
        )
        self.assertIs(hunt.evaluate(entry, facts()), hunt.Status.VULNERABLE)

    def test_max_sdk(self):
        entry = hunt.Entry(id="CVE-X", title="t", component="framework", max_sdk=33)
        self.assertIs(hunt.evaluate(entry, facts()), hunt.Status.PATCHED)

    def test_platform_mismatch(self):
        entry = hunt.Entry(
            id="CVE-X",
            title="t",
            component="gpu",
            platform="qualcomm",
            fixed_security_patch="2020-01-01",
        )
        self.assertIs(hunt.evaluate(entry, facts()), hunt.Status.NOT_APPLICABLE)

    def test_kernel_out_of_range(self):
        entry = hunt.Entry(id="CVE-X", title="t", component="kernel", max_kernel="5.16.10")
        self.assertIs(hunt.evaluate(entry, facts()), hunt.Status.NOT_APPLICABLE)

    def test_unknown_patch_level(self):
        entry = hunt.Entry(
            id="CVE-X", title="t", component="kernel", fixed_security_patch="2026-01-01"
        )
        self.assertIs(hunt.evaluate(entry, facts(security_patch=None)), hunt.Status.UNKNOWN)

    def test_bundled_catalog_flags_cve_2026_98260(self):
        catalog = hunt.load_catalog()
        self.assertGreater(len(catalog.entries), 0)
        vulnerable = [
            entry.id
            for entry in catalog.entries
            if hunt.evaluate(entry, facts()) is hunt.Status.VULNERABLE
        ]
        self.assertEqual(vulnerable, ["CVE-2026-98260"])


class CatalogTest(unittest.TestCase):
    def test_rejects_entry_without_constraints(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "entries": [{"id": "CVE-X", "title": "t", "component": "kernel"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(LapisRootError):
                hunt.load_catalog(path)


class PocTest(unittest.TestCase):
    def test_manifest_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "CVE-X"
            directory.mkdir()
            (directory / "manifest.json").write_text(
                json.dumps({"command": ["./poc"], "timeout": 5, "expected": "uid=0"}),
                encoding="utf-8",
            )
            entry = hunt.Entry(
                id="CVE-X", title="t", component="kernel", fixed_security_patch="2020-01-01"
            )
            spec = hunt.find_poc(entry, Path(temp))
            self.assertIsNotNone(spec)
            self.assertEqual(spec.command, ("./poc",))
            self.assertEqual(spec.timeout, 5)
            self.assertEqual(spec.cwd, str(directory))

    def test_run_sh_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "CVE-Y"
            directory.mkdir()
            (directory / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            entry = hunt.Entry(
                id="CVE-Y", title="t", component="kernel", fixed_security_patch="2020-01-01"
            )
            spec = hunt.find_poc(entry, Path(temp))
            self.assertEqual(spec.command[0], "sh")


class FactsTest(unittest.TestCase):
    def test_collect_facts(self):
        collected = hunt.collect_facts("SER", runner=make_runner())
        self.assertEqual(collected.codename, "lapis")
        self.assertEqual(collected.sdk, 36)
        self.assertEqual(collected.security_patch, "2026-09-01")
        self.assertEqual(collected.kmi, "android14-6.1")
        self.assertEqual(collected.selinux, "Enforcing")
        self.assertIs(collected.debuggable, False)


class HuntFlowTest(unittest.TestCase):
    def test_reports_and_executes_only_a_local_poc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "entries": [
                            {
                                "id": "CVE-PATCHED",
                                "title": "patched",
                                "component": "kernel",
                                "fixed_security_patch": "2026-01-01",
                            },
                            {
                                "id": "CVE-OPEN",
                                "title": "open",
                                "component": "kernel",
                                "fixed_security_patch": "2027-01-01",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            poc_dir = root / "pocs" / "CVE-OPEN"
            poc_dir.mkdir(parents=True)
            (poc_dir / "manifest.json").write_text(
                json.dumps({"command": ["./poc"], "timeout": 5}), encoding="utf-8"
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = hunt.hunt(
                    hunt.HuntOptions(
                        serial="SER",
                        catalog=catalog,
                        poc_dir=root / "pocs",
                        state_dir=root / "state",
                        execute=True,
                        assume_yes=True,
                        json_report=True,
                        runner=make_runner(),
                    )
                )

            self.assertEqual(rc, 0)
            text = output.getvalue()
            self.assertIn("CVE-PATCHED", text)
            self.assertIn("CVE-OPEN", text)
            self.assertIn("uid=0", text)
            reports = list((root / "state" / "reports").glob("hunt-*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(report["results"][0]["id"], "CVE-OPEN")
            self.assertEqual(report["facts"]["codename"], "lapis")


if __name__ == "__main__":
    unittest.main()
