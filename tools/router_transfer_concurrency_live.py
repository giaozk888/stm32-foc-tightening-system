"""Bounded electrically isolated acceptance: local bench + real network reads.

No flash/reset/motion/parameter/power commands. --permit-isolated-test is
required to run the fixed 60 s compute-only fixture on its dedicated firmware.
The finally path stops the fixture even when a network request fails.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
import serial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from router_network.transfer_client import run as transfer_run
from router_network.rpc_live_acceptance import run as rpc_run
from router_network.transfer_wire import decode_encoder
from router_network.node import endpoint

ALLOWED = {"PING", "FW STATUS", "STATUS", "ANALOG SAFE STATUS", "ENC DIAG",
           "ADC TIMING", "ADC BUFFER", "BENCH RUN", "BENCH STOP", "BENCH STATUS", "BENCH STACK",
           "ROUTER STATUS"}


class Console:
    def __init__(self, port, evidence):
        self.records = []
        self.evidence = evidence
        self.sequence = 47000
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=.03, write_timeout=2)
        self.serial.dtr = self.serial.rts = False
        self.serial.port = port
        self.serial.open()

    async def request(self, command):
        assert command in ALLOWED
        self.sequence += 1
        seq = self.sequence
        self.serial.write(f"{seq} {command}\r\n".encode())
        deadline = time.monotonic() + 5
        replies = []
        while time.monotonic() < deadline:
            line = self.serial.readline().decode(errors="replace").strip()
            if re.match(rf"^{seq} (OK|ERR) ", line):
                replies.append(line)
                self.records.append({"time": time.time(), "command": command, "reply": line})
                print(line, flush=True)
                if command != "ENC DIAG" or "ENC STACK" in line or " ERR " in line:
                    assert " ERR " not in line, line
                    return replies
            await asyncio.sleep(.002)
        raise TimeoutError(command)

    def close(self):
        self.serial.close()
        (self.evidence / "console.json").write_text(json.dumps(self.records, indent=2), encoding="utf-8")


def fields(reply):
    return {name: int(value) for name, value in re.findall(r"([A-Z_]+)=(\d+)(?=\s|$)", reply)}


async def network(args, evidence, outputs):
    helper = ROOT / "tests/router_transfer_host/build/router_transfer_client.exe"
    for turn, resource in enumerate((3, 4, 3, 4)):
        output = evidence / f"network-resource-{resource}-{turn}.bin"
        await transfer_run(SimpleNamespace(helper=str(helper), node=4, resource=resource,
                           tcp=args.tcp, usb_serial=None, output=str(output)))
        data = output.read_bytes()
        assert data, "Empty history cannot qualify a download"
        record = {"resource": resource, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if resource == 4:
            record["encoder"] = decode_encoder(data)
            assert record["encoder"]["status"] == 0 and record["encoder"]["age_us"] < 5000
        outputs.append(record)
        (evidence / "transfer-progress.json").write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    return outputs


async def run(args, evidence):
    console = Console(args.port, evidence)
    tasks = []
    result = {"pass": False, "hardware": True, "power_stage_enabled": False,
              "motor_commands_sent": False, "topology_confirmed": False,
              "rpc_mode": args.rpc_mode, "transfers": [], "samples": [], "rpc": {}}
    try:
        fw = (await console.request("FW STATUS"))[0]
        assert "CURRENT=A" in fw and "CONFIRMED=A" in fw and "PENDING=-" in fw and "ACTIVE=0" in fw
        safe = (await console.request("ANALOG SAFE STATUS"))[0]
        assert "LATCHED=1 SD=0 MOE=0 FOC=0" in safe
        before = {cmd: fields((await console.request(cmd))[0]) for cmd in ("ADC TIMING", "ADC BUFFER", "ROUTER STATUS")}
        result["before"] = before
        start = fields((await console.request("BENCH RUN"))[0])
        assert start["ACTIVE"] == start["LOCK"] == start["CEN"] == 1
        assert start["SD"] == start["MOE"] == start["CCER"] == 0
        tasks = [asyncio.create_task(network(args, evidence, result["transfers"])),
                 asyncio.create_task(rpc_run(SimpleNamespace(node=5, rounds=10, tcp=args.tcp, usb_serial=None,
                                                            rpc_mode=args.rpc_mode, progress=result["rpc"])))]
        samples = result["samples"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            sample = fields((await console.request("BENCH STATUS"))[0])
            assert sample["ACTIVE"] == sample["LOCK"] == 1
            assert sample["SD"] == sample["MOE"] == sample["CCER"] == 0
            if samples:
                elapsed = sample["MS"] - samples[-1]["MS"]
                assert elapsed > 0
                for counter in ("ADC", "FOC"):
                    rate = (sample[counter] - samples[-1][counter]) * 1000 / elapsed
                    assert 18000 < rate < 22000, (counter, rate)
            samples.append(sample)
            if all(task.done() for task in tasks):
                break
        else:
            raise TimeoutError("45 second concurrent acceptance limit")
        transfers = await tasks[0]
        result["rpc_summary"] = await tasks[1]
        assert len(samples) >= 2
        after = {cmd: fields((await console.request(cmd))[0]) for cmd in ("ADC TIMING", "ADC BUFFER", "BENCH STACK", "ROUTER STATUS")}
        result["after"] = after
        for field in ("MISS", "LATE", "PF"):
            assert after["ADC TIMING"][field] == before["ADC TIMING"][field], (field, before, after)
        for field in ("DROP_B", "DROP_S", "REJECT"):
            assert after["ADC BUFFER"][field] == before["ADC BUFFER"][field], (field, before, after)
        for field in ("RXQFULL", "LOCALQFULL", "PARSE", "NOROUTE"):
            assert after["ROUTER STATUS"][field] == before["ROUTER STATUS"][field], (field, before, after)
        assert after["ADC BUFFER"]["DONE"] > before["ADC BUFFER"]["DONE"]
        assert after["ADC BUFFER"]["STK_VALID"] == 1 and after["ADC BUFFER"]["FREE_B"] >= 256
        for field in ("MOTOR", "ROUTER", "PROTO", "TRANSFER"):
            assert after["BENCH STACK"][field] >= 256, (field, after)
        await console.request("ENC DIAG")
        result.update(pass_=True, transfers=transfers, before=before, after=after, samples=samples,
                      duration_ms=samples[-1]["MS"], adc_pairs=samples[-1]["ADC"],
                      foc_calculations=samples[-1]["FOC"])
        result["pass"] = result.pop("pass_")
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            result["stopped"] = (await console.request("BENCH STOP"))[0]
            result["final_safe"] = (await console.request("ANALOG SAFE STATUS"))[0]
            result["final_status"] = (await console.request("STATUS"))[0]
            assert "SD=0 MOE=0 CCER=0 CEN=0" in result["stopped"]
            assert "LATCHED=1 SD=0 MOE=0 FOC=0" in result["final_safe"]
            assert "FLT=0" in result["final_status"]
            # Preserve diagnostic evidence on failure too; a timeout must not
            # erase the completed downloads or hide ADC/task counters.
            if "after" not in result:
                result["after"] = {cmd: fields((await console.request(cmd))[0]) for cmd in
                                   ("ADC TIMING", "ADC BUFFER", "BENCH STACK", "ROUTER STATUS")}
        except Exception as error:
            result["pass"] = False
            result["cleanup_error"] = str(error)
            raise
        finally:
            console.close()
            (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("REAL NETWORK + ISOLATED FREERTOS/FOC CONCURRENCY PASS", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--tcp", type=endpoint, default=("192.168.137.10", 21000))
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--permit-isolated-test", action="store_true")
    parser.add_argument("--rpc-mode", choices=("burst", "paced"), default="paced",
                        help="paced: two peers, one in-flight call each; burst: eight simultaneous calls")
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if not evidence.is_relative_to((ROOT / "safety_backups").resolve()) or evidence.exists():
        parser.error("Choose a NEW evidence directory within workspace safety_backups")
    if not args.permit_isolated_test:
        parser.error("Fresh electrical isolation and fixed compute-only test permission required")
    evidence.mkdir(parents=True)
    asyncio.run(run(args, evidence))


if __name__ == "__main__":
    main()
