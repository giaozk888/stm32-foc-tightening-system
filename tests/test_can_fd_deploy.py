import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("can_fd_deploy", TOOLS / "can_fd_deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class GuardTest(unittest.TestCase):
    def test_missing_linux_binary_prevents_prepare(self):
        with patch.object(deploy, "__file__", str(deploy.ROOT / "controller.py")), \
             patch.object(deploy, "BINARY") as binary, patch.object(deploy.base, "prepare") as prepare:
            binary.is_file.return_value = False
            with self.assertRaises(RuntimeError):
                deploy.prepare()
            prepare.assert_not_called()

    def test_release_classic_cannot_release_running_fd_device_tree(self):
        marker = Mock()
        marker.read_text.return_value = '{"original_sha256":"original"}'
        with patch.object(deploy, "ROOT", Mock(__truediv__=Mock(return_value=marker))), \
             patch.object(deploy.base, "BOOT") as boot, \
             patch.object(deploy.base, "digest", return_value="original"), \
             patch.object(deploy.setup, "compatible", return_value=deploy.setup.EXPECTED_COMPATIBLE), \
             patch.object(deploy.base, "remove_owned") as remove:
            boot.read_bytes.return_value = b"original"
            with self.assertRaises(RuntimeError):
                deploy.release_classic(True)
            remove.assert_not_called()

    def test_live_profile_failure_does_not_transmit_or_mutate(self):
        with patch.object(deploy.setup, "inspect", return_value={}), \
             patch.object(deploy.setup, "matches_profile", return_value=False), \
             patch.object(deploy.base, "run") as run:
            with self.assertRaises(RuntimeError):
                deploy.check_errors()
            run.assert_not_called()

    def test_kernel_errors_reject_commit_preflight(self):
        for interface in (
            {"stats64": {"rx": {"errors": 1}}},
            {"stats64": {}, "linkinfo": {"info_xstats": {"bus_off": 1}}},
        ):
            with patch.object(deploy.setup, "inspect", return_value=interface), \
                 patch.object(deploy.setup, "matches_profile", return_value=True):
                with self.assertRaises(RuntimeError):
                    deploy.check_errors()


if __name__ == "__main__":
    unittest.main()
