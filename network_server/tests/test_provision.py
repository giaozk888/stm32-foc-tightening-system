import os
import importlib.util
from pathlib import Path
import tempfile
import io
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch
from tools.provision_gateway import main, check_lubancat_api_token, lubancat_hotspot_password

class ProvisionTests(unittest.TestCase):
    def test_hotspot_auto_config_only_prompts_for_api_and_hides_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            argv=["provision_gateway.py","--interactive","--lubancat-hotspot","--ssid","LubanCat-ESP32","--url","http://192.168.50.1:18089/api/v1/observations","--allow-lan-http","--output",str(Path(directory)/"nvs.bin")]
            password="a"*32; token="synthetic-api-secret-only-00000000"; output=io.StringIO()
            with patch("sys.argv",argv), patch("tools.provision_gateway.lubancat_hotspot_password",return_value=password), patch("tools.provision_gateway.check_lubancat_api_token") as probe, patch("getpass.getpass",return_value=token) as prompt, patch("subprocess.run") as run, redirect_stdout(output):
                main()
            self.assertEqual(prompt.call_count,1); probe.assert_called_once_with(token)
            self.assertNotIn(password,output.getvalue()); self.assertNotIn(token,output.getvalue())
            self.assertEqual(run.call_args.args[0][1:4],["-m","esp_idf_nvs_partition_gen","generate"])
    def test_hotspot_api_failure_does_not_generate_image(self):
        argv=["provision_gateway.py","--lubancat-hotspot","--ssid","LubanCat-ESP32","--url","http://192.168.50.1:18089/api/v1/observations","--allow-lan-http"]
        with patch("sys.argv",argv), patch("tools.provision_gateway.lubancat_hotspot_password",return_value="a"*32), patch("tools.provision_gateway.check_lubancat_api_token",side_effect=RuntimeError("synthetic failure")), patch("getpass.getpass",return_value="synthetic-api-secret-only-00000000"), patch("subprocess.run") as run:
            with self.assertRaises(SystemExit):main()
            run.assert_not_called()
    def test_hotspot_secret_capture_and_probe_transport(self):
        with patch("tools.provision_gateway._lubancat_ssh",return_value="b"*32+"\n"):
            self.assertEqual(lubancat_hotspot_password(),"b"*32)
        token="synthetic-api-secret-only-00000000"
        with patch("tools.provision_gateway._lubancat_ssh",return_value="200\n") as ssh:
            check_lubancat_api_token(token)
            command, stdin=ssh.call_args.args
            self.assertNotIn(token,command); self.assertEqual(stdin,token)
    def test_invalid_wifi_password_rejected_before_api_prompt(self):
        argv=["provision_gateway.py","--ssid","Test","--url","https://example.test/api/v1/observations"]
        with patch("sys.argv",argv), patch("getpass.getpass",return_value="short") as prompt, patch("subprocess.run") as run:
            with self.assertRaises(SystemExit):main()
            self.assertEqual(prompt.call_count,1); run.assert_not_called()
    def test_offline_config_and_no_flash_command(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/"nvs.bin"
            argv=["provision_gateway.py","--ssid","Test-WiFi","--url","http://192.168.137.10:18089/api/v1/observations","--allow-lan-http","--output",str(out)]
            with patch("sys.argv",argv), patch("getpass.getpass",return_value="test-password"), patch.dict(os.environ,{"TIGHTEN_API_TOKEN":"test-provision-token-only-000000000"}), patch("subprocess.run") as run:
                main()
            command=run.call_args.args[0]
            self.assertEqual(command[1:4],["-m","esp_idf_nvs_partition_gen","generate"])
            self.assertEqual(command[-1],"0x6000")
            self.assertNotIn("flash",command)
            self.assertFalse(Path(command[4]).exists()) # temporary CSV removed
    def test_plain_http_requires_opt_in(self):
        with patch("sys.argv",["provision_gateway.py","--ssid","Test","--url","http://127.0.0.1:8088/api/v1/observations"]):
            with self.assertRaises(SystemExit):main()
    def test_control_character_in_token_rejected(self):
        argv=["provision_gateway.py","--ssid","Test","--url","https://example.test/api/v1/observations"]
        with patch("sys.argv",argv), patch("getpass.getpass",return_value="test-password"), patch.dict(os.environ,{"TIGHTEN_API_TOKEN":"test-token-000000000000000\x01"}), patch("subprocess.run") as run:
            with self.assertRaises(SystemExit):main()
            run.assert_not_called()
    def test_loopback_and_public_http_rejected_before_secrets(self):
        for origin in ("http://127.0.0.1:18089", "https://localhost", "http://118.25.40.152:18088", "http://example.test", "http://0.0.0.0"):
            argv=["provision_gateway.py","--ssid","Test","--url",origin+"/api/v1/observations","--allow-lan-http"]
            with self.subTest(origin=origin), patch("sys.argv",argv), patch("getpass.getpass") as secret, patch("subprocess.run") as run:
                with self.assertRaises(SystemExit):main()
                secret.assert_not_called();run.assert_not_called()
    def test_interactive_private_lan_and_fresh_token_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            argv=["provision_gateway.py","--interactive","--output",str(Path(directory)/"nvs.bin")]
            with patch("sys.argv",argv), patch("builtins.input",side_effect=["Test-WiFi","http://192.168.137.10:18089/api/v1/observations","LAN"]), patch("getpass.getpass",side_effect=["test-password","test-fresh-server-token-00000000"]) as secret, patch.dict(os.environ,{"TIGHTEN_API_TOKEN":"stale-env-token-00000000000000"}), patch("subprocess.run") as run:
                main()
                self.assertEqual(secret.call_count,2)
                self.assertEqual(run.call_args.args[0][-1],"0x6000")
    @unittest.skipUnless(importlib.util.find_spec("esp_idf_nvs_partition_gen"), "ESP-IDF Python required")
    def test_real_nvs_generator_with_synthetic_credentials(self):
        with tempfile.TemporaryDirectory(prefix="gateway-nvs-test-") as directory:
            out=Path(directory)/"nvs.bin"
            argv=["provision_gateway.py","--ssid","Synthetic-Test","--url","https://example.test/api/v1/observations","--output",str(out)]
            with patch("sys.argv",argv), patch("getpass.getpass",return_value="synthetic-password"), patch.dict(os.environ,{"TIGHTEN_API_TOKEN":"synthetic-token-only-000000000"}):
                main()
            self.assertEqual(out.stat().st_size,0x6000)

if __name__=="__main__":unittest.main()
