"""Verify application and provisioned NVS values without printing any secrets."""
from pathlib import Path
import sys
import json
import hashlib
import argparse

sys.path.insert(0, "D:/Espressif/v6.1/esp-idf/components/nvs_flash/nvs_partition_tool")
from nvs_parser import NVS_Partition

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--evidence", type=Path, default=root / "safety_backups/20261005-router-live-acceptance")
parser.add_argument("--app", type=Path, default=root / "esp32_s3_gateway/build_router/stm32_esp32_gateway.bin")
args = parser.parse_args()
evidence = args.evidence.resolve()
assert (root / "safety_backups").resolve() in evidence.parents, "Private backups must remain under safety_backups"
before = (evidence / "esp32-before-private.bin").read_bytes()
after = (evidence / "esp32-after-private.bin").read_bytes()
app = args.app.read_bytes()
assert len(before) == len(after) == 0x110000, "Backup lengths differ"
assert before[:0x9000] == after[:0x9000], "Bootloader/partition table changed"
assert before[0xf000:0x10000] == after[0xf000:0x10000], "PHY partition changed"
assert after[0x10000:0x10000 + len(app)] == app, "Application readback differs"


def gateway_values(raw):
    partition = NVS_Partition("private", bytearray(raw[0x9000:0xf000]))
    pages = sorted((p for p in partition.pages if p.header["status"] in ("Active", "Full")),
                   key=lambda p: p.header["page_index"])
    namespace = None
    for page in pages:
        for entry in page.entries:
            if entry.state == "Written" and entry.metadata["namespace"] == 0 and entry.key == "gateway":
                assert entry.metadata["crc"]["original"] == entry.metadata["crc"]["computed"], "Namespace CRC"
                namespace = entry.data["value"]
    assert namespace is not None, "Provisioning namespace missing"
    values = {}
    for page in pages:
        for entry in page.entries:
            if entry.state != "Written" or entry.metadata["namespace"] != namespace:
                continue
            assert entry.metadata["crc"]["original"] == entry.metadata["crc"]["computed"], "NVS entry CRC"
            if entry.metadata["type"] == "string":
                value = bytes(b for child in entry.children for b in child.raw)[:entry.data["size"]]
                assert entry.metadata["crc"]["data_original"] == entry.metadata["crc"]["data_computed"], "NVS data CRC"
            elif entry.metadata["type"] == "uint8_t":
                value = entry.data["value"]
            else:
                raise AssertionError("Unexpected provisioning entry type")
            values[entry.key] = value
    assert set(values) == {"ssid", "pass", "url", "token", "allow_http"}, "Provisioning key set differs"
    return values


assert gateway_values(before) == gateway_values(after), "Provisioned values changed; values deliberately hidden"
result = {"result": "PASS", "app_bytes": len(app),
          "app_sha256": hashlib.sha256(app).hexdigest(),
          "bootloader_partition_table_phy_unchanged": True,
          "gateway_ssid_password_url_token_allow_http_unchanged": True,
          "nvs_raw_bytes_unchanged": before[0x9000:0xf000] == after[0x9000:0xf000],
          "secret_values_printed": False}
(evidence / "esp32-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
