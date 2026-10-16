import importlib.util
from pathlib import Path
import unittest
spec = importlib.util.spec_from_file_location(
    "report", Path(__file__).resolve().parents[1] / "tools/foc_adc_spread_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def line(ch, mix=0, block=1):
    return (f"1 OK ADC SPREAD {ch} B={block} N=256 SUM=524288 SS=1073742080 "
            f"MIN=2047 MAX=2049 STEP=2 MIX={mix} CMDU=2125 CMDV=2125 CMDW=2125 CMD4=3271")


class ReportTest(unittest.TestCase):
    def test_known_variance(self):
        result = report.analyze(line("U") + "\n" + line("V"))
        u = result["accepted_blocks"][0]["channels"]["U"]
        self.assertEqual(u["mean_counts"], 2048)
        self.assertEqual(u["population_stddev_counts"], 1)
        self.assertFalse(result["physical_conditions_verified"])

    def test_mixed_excluded(self):
        self.assertFalse(report.analyze(line("U", 1) + "\n" + line("V", 1))["accepted_blocks"])

    def test_duplicate_not_double_counted(self):
        self.assertEqual(len(report.analyze(line("U") + "\n" + line("U") + "\n" + line("V"))["accepted_blocks"]), 1)

    def test_unpaired_and_mismatched(self):
        self.assertFalse(report.analyze(line("U") + "\n" + line("V", block=2))["accepted_blocks"])
        self.assertFalse(report.analyze(line("U") + "\n" + line("V").replace("CMD4=3271", "CMD4=3272"))["accepted_blocks"])

    def test_invalid_variance(self):
        with self.assertRaises(ValueError):
            report.analyze(line("U").replace("SS=1073742080", "SS=1073740000") + "\n" + line("V"))


if __name__ == "__main__":
    unittest.main()
