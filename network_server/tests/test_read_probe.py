import contextlib
import io
import unittest
from unittest.mock import patch

from tools import network_read_probe


class ReadProbeTests(unittest.TestCase):
    def run_probe(self, flags=9, quality=1, fresh=True):
        registers = [0] * 40
        registers[0:4] = [1, 3 if fresh else 1, 0, quality]
        registers[7] = 77
        registers[15] = flags
        registers[23] = 1500  # Must not appear as valid Iq in safe mode.
        registers[25] = 11700
        output = io.StringIO()
        with patch("sys.argv", ["probe", "--esp-ip", "192.0.2.1"]), \
                patch.object(network_read_probe, "read_inputs",
                             side_effect=lambda host, port, addr, qty, tid:
                             tuple(registers[addr:addr + qty])) as read, \
                contextlib.redirect_stdout(output):
            network_read_probe.main()
        return output.getvalue(), read.call_count

    def test_safe_sample_does_not_present_old_iq_as_valid(self):
        output, calls = self.run_probe()
        self.assertIn("safe=True", output)
        self.assertIn("iq_ma=unavailable", output)
        self.assertNotIn("iq_ma=1500", output)
        self.assertEqual(calls, 2)

    def test_invalid_fields_are_unavailable(self):
        output, _ = self.run_probe(flags=8, quality=3)
        for field in ("position_deg", "rpm", "iq_ma", "bus_est_mv"):
            self.assertIn(field + "=unavailable", output)

    def test_stale_sample_only_reads_gateway_diagnostics(self):
        output, calls = self.run_probe(fresh=False)
        self.assertIn("fresh=False", output)
        self.assertNotIn("position_deg=", output)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
