import unittest

from upper_computer.server import Monitor


class MonitorTests(unittest.TestCase):
    def test_decodes_status_firmware_router_and_analog(self):
        monitor = Monitor()
        monitor._handle_line("1001 OK STATUS MODE=IDLE FLT=0 POS=0.04deg")
        monitor._handle_line("1002 OK FW STATUS CURRENT=B CONFIRMED=B PENDING=-")
        monitor._handle_line("1003 OK ROUTER NODE=1 DRX=297 DTX=595 PARSE=0")
        monitor._handle_line("1004 OK ANALOG VOLT VALID=1 VBUS_EST_MV=11792 VTEMP_MV=1077")
        monitor._handle_line("1005 NODE ID=2 PORT=ESP32 AGE_MS=3137")
        fields = monitor.snapshot()["fields"]
        self.assertEqual(fields["mode"], "IDLE")
        self.assertEqual(fields["fault"], "0")
        self.assertEqual(fields["slot"], "B")
        self.assertEqual(fields["confirmed"], "B")
        self.assertEqual(fields["parse_errors"], "0")
        self.assertEqual(fields["vbus_v"], 11.792)
        self.assertTrue(fields["esp"].startswith("在线"))

    def test_samples_and_ping(self):
        monitor = Monitor()
        monitor._handle_line("RTOS-FOC MODE=IDLE FLT=0 POS=0.02deg FOC/s=20004 Iq=52mA")
        monitor._handle_line("1006 OK ESP32 PONG")
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot["samples"][0]["position"], 0.02)
        self.assertEqual(snapshot["samples"][0]["iq"], 52.0)
        self.assertEqual(snapshot["fields"]["ping"], "请求 1006 成功")


if __name__ == "__main__":
    unittest.main()
