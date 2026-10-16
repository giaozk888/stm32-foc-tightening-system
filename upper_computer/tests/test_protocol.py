import unittest

from upper_computer.protocol import number, parse_line, request_line


class ProtocolTests(unittest.TestCase):
    def test_telemetry_fields(self):
        line = (
            "RTOS-FOC CYCLE=1/1 MODE=IDLE t=3000ms | ADC/s=20004 "
            "FOC/s=20004 EN=1 FLT=0 | POS=-0.04 PTGT=0.00 | "
            "IqCmd=0mA IqRef=0mA | Id=12mA Iq=-32mA"
        )
        message = parse_line(line)
        self.assertEqual(message.kind, "telemetry")
        self.assertEqual(message.fields["MODE"], "IDLE")
        self.assertEqual(message.fields["FOC/s"], "20004")
        self.assertEqual(number(message.fields["POS"]), -0.04)
        self.assertEqual(number(message.fields["Iq"]), -32)

    def test_status_and_firmware(self):
        status = parse_line("5100 OK STATUS MODE=IDLE FLT=0 POS=0.02deg")
        firmware = parse_line(
            "5102 OK FW CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0"
        )
        self.assertEqual(status.kind, "status")
        self.assertEqual(number(status.fields["POS"]), 0.02)
        self.assertEqual(firmware.kind, "firmware")
        self.assertEqual(firmware.fields["CONFIRMED"], "B")

    def test_router_and_esp_reply(self):
        node = parse_line("4201 NODE ID=2 PORT=ESP32 AGE_MS=4791 RX=7")
        reply = parse_line("4203 OK ESP32 PONG")
        timeout = parse_line("4203 ERR 104 ESP_PING_TIMEOUT")
        self.assertEqual(node.kind, "nodes")
        self.assertEqual(node.fields["ID"], "2")
        self.assertEqual(reply.kind, "esp_ping")
        self.assertTrue(reply.ok)
        self.assertEqual(timeout.kind, "esp_ping")
        self.assertFalse(timeout.ok)

    def test_numbers(self):
        self.assertEqual(number("1080mV"), 1080)
        self.assertIsNone(number("—"))
        self.assertIsNone(number(None))

    def test_only_safe_requests(self):
        self.assertEqual(request_line(3014, "ESP PING"), b"3014 ESP PING\r\n")
        with self.assertRaises(ValueError):
            request_line(1, "START")
        with self.assertRaises(ValueError):
            request_line(65536, "STATUS")


if __name__ == "__main__":
    unittest.main()
