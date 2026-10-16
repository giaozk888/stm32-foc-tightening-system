import copy
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("can_fd_setup",
    Path(__file__).resolve().parents[1] / "tools/can_fd_communication_setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def active_profile():
    return {"mtu": 72, "flags": ["UP"], "linkinfo": {"info_kind": "can", "info_data": {
        "ctrlmode": ["FD"], "state": "ERROR-ACTIVE",
        "bittiming": {"bitrate": 500000}, "data_bittiming": {"bitrate": 500000},
        "restart_ms": 0, "berr_counter": {"tx": 0, "rx": 0}}}}


class SetupTest(unittest.TestCase):
    def test_live_profile_no_interruption(self):
        with patch.object(setup, "inspect", return_value=active_profile()), \
             patch.object(setup, "compatible", return_value=setup.EXPECTED_COMPATIBLE), \
             patch.object(setup, "run") as run:
            result = setup.setup(True)
            self.assertTrue(result["profile_ready"])
            self.assertFalse(result["modified"])
            run.assert_not_called()

    def test_inspection_only_never_configures(self):
        down = active_profile()
        down["flags"] = []
        with patch.object(setup, "inspect", return_value=down), \
             patch.object(setup, "compatible", return_value=setup.EXPECTED_COMPATIBLE), \
             patch.object(setup, "run") as run:
            self.assertFalse(setup.setup()["profile_ready"])
            run.assert_not_called()

    def test_wrong_device_tree_refused(self):
        with patch.object(setup, "inspect", return_value=active_profile()), \
             patch.object(setup, "compatible", return_value=b"rockchip,rk3568-can-2.0"), \
             patch.object(setup, "run") as run:
            with self.assertRaises(RuntimeError):
                setup.setup(True)
            run.assert_not_called()

    def test_unexpected_live_bus_never_interrupted(self):
        for changes in ({"ctrlmode": []}, {"ctrlmode": ["FD", "LOOPBACK"]},
                        {"data_bittiming": {"bitrate": 2000000}}, {"restart_ms": 100},
                        {"berr_counter": {"tx": 1, "rx": 0}}, {"state": "BUS-OFF"}):
            interface = active_profile()
            interface["linkinfo"]["info_data"].update(changes)
            with self.subTest(changes=changes), \
                 patch.object(setup, "inspect", return_value=interface), \
                 patch.object(setup, "compatible", return_value=setup.EXPECTED_COMPATIBLE), \
                 patch.object(setup, "run") as run:
                with self.assertRaises(RuntimeError):
                    setup.setup(True)
                run.assert_not_called()

    def test_down_interface_configures_exact_profile(self):
        down = copy.deepcopy(active_profile())
        down["flags"] = []
        with patch.object(setup, "inspect", side_effect=[down, active_profile()]), \
             patch.object(setup, "compatible", return_value=setup.EXPECTED_COMPATIBLE), \
             patch.object(setup, "run") as run:
            result = setup.setup(True)
            self.assertTrue(result["modified"])
            self.assertTrue(result["profile_ready"])
            self.assertEqual(run.call_args_list[0].args,
                ("ip", "link", "set", "can0", "type", "can", "bitrate", "500000",
                 "dbitrate", "500000", "fd", "on", "restart-ms", "0"))
            self.assertEqual(run.call_count, 2)

    def test_failed_start_closes_interface(self):
        down = active_profile()
        down["flags"] = []
        with patch.object(setup, "inspect", return_value=down), \
             patch.object(setup, "compatible", return_value=setup.EXPECTED_COMPATIBLE), \
             patch.object(setup, "run", side_effect=["", subprocess.CalledProcessError(1, "up"), ""]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.setup(True)
            self.assertEqual(run.call_args_list[-1].args, ("ip", "link", "set", "can0", "down"))

    def test_failed_verification_closes_interface(self):
        down = active_profile()
        down["flags"] = []
        invalid = active_profile()
        invalid["mtu"] = 16
        with patch.object(setup, "inspect", side_effect=[down, invalid]), \
             patch.object(setup, "compatible", return_value=setup.EXPECTED_COMPATIBLE), \
             patch.object(setup, "run") as run:
            with self.assertRaises(RuntimeError):
                setup.setup(True)
            self.assertEqual(run.call_args_list[-1].args, ("ip", "link", "set", "can0", "down"))


if __name__ == "__main__":
    unittest.main()
