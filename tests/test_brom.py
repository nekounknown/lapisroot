import unittest

from lapisroot.brom import format_report, parse_report

UNPROTECTED = """
Port - Device detected :)
Preloader - Detected regular mode !
Preloader - CPU: MT6878(Dimensity 7300)
Preloader - SBC enabled: False
Preloader - SLA enabled: False
Preloader - DAA enabled: False
DaHandler - Device is unprotected.
"""

PROTECTED = """
Preloader - CPU: MT6878(Dimensity 7400)
Preloader - SBC enabled: True
Preloader - SLA enabled: True
Preloader - DAA enabled: True
DaHandler - Device is still protected, trying to boot to brom
Preloader - [LIB]: upload_data failed with error: DAA_SIG_VERIFY_FAILED (0x7024)
"""

MISSING_LOADER = """
Preloader - CPU: MT6878(Dimensity 7300)
Preloader - DAA enabled: False
DAconfig - [LIB]: No valid da loader found... aborting.
"""


class BromParseTest(unittest.TestCase):
    def test_unprotected_device(self):
        report = parse_report(UNPROTECTED)
        self.assertIn("MT6878", report.cpu)
        self.assertIs(report.sbc, False)
        self.assertIs(report.sla, False)
        self.assertIs(report.daa, False)
        self.assertIs(report.unprotected, True)
        self.assertTrue(report.write_possible)

    def test_daa_failure_blocks_write(self):
        report = parse_report(PROTECTED)
        self.assertIs(report.daa, True)
        self.assertIs(report.unprotected, False)
        self.assertTrue(report.daa_verify_failed)
        self.assertFalse(report.write_possible)

    def test_missing_da_loader_blocks_write(self):
        report = parse_report(MISSING_LOADER)
        self.assertTrue(report.da_loader_missing)
        self.assertFalse(report.write_possible)

    def test_format_report_explains_outcome(self):
        lines = format_report(parse_report(PROTECTED))
        text = "\n".join(lines)
        self.assertIn("DAA_SIG_VERIFY_FAILED", text)
        self.assertIn("blocked", text)


if __name__ == "__main__":
    unittest.main()
