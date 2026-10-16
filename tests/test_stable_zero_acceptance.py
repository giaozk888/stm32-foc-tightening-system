"""Pure offline observer gates: never opens a port/probe."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from stable_zero_acceptance import require_zero, require_running, require_idle, ZeroUart

class ObserverTests(unittest.TestCase):
    def test_zero_requires_full_window_and_raw_spread(self):
        good = "OK BENCH ZERO STATE=3 REASON=0 NOM=1560 U0=1560 V0=1565 N=4000 SET=20000 RET=0 RNG=1558:1562,1563:1567"
        require_zero(good)
        for old, new in (("STATE=3", "STATE=4"), ("REASON=0", "REASON=3"),
            ("N=4000", "N=3999"), ("SET=20000", "SET=19999"),
            ("RET=0", "RET=8"), ("U0=1560", "U0=1853"),
            ("RNG=1558:1562", "RNG=1558:1580")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                require_zero(good.replace(old, new))

    def test_run_requires_ready_zero_and_every_output_off(self):
        good = "OK BENCH ACTIVE=1 ZERO=1 LOCK=1 SD=0 MOE=0 CCER=0 CEN=1"
        require_running(good)
        for old, new in (("ACTIVE=1", "ACTIVE=0"), ("ZERO=1", "ZERO=0"),
            ("LOCK=1", "LOCK=0"), ("SD=0", "SD=1"),
            ("MOE=0", "MOE=1"), ("CCER=0", "CCER=4"), ("CEN=1", "CEN=0")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                require_running(good.replace(old, new))

    def test_existing_faults_and_motion_are_refused(self):
        good = "OK MODE=IDLE BUSY=0 START_REQ=0 IqRef=0mA FLT=0 REASON=0"
        require_idle(good)
        with self.assertRaises(RuntimeError):
            require_idle(good.replace("FLT=0", "FLT=1"))
        class NoPort:
            def write(self, data):
                raise AssertionError("Rejected command reached UART")
        for permit in (False, True):
            uart = ZeroUart(NoPort(), permit)
            for command in ("START", "CLEAR", "BOOT B", "FW BEGIN 32 12345678", "FW END", "SIM RUN"):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    uart.query(command)
        with self.assertRaises(ValueError):
            ZeroUart(NoPort()).query("BENCH RUN")

if __name__ == "__main__":
    unittest.main()
