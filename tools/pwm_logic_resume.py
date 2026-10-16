"""Recover the saved SAFE context after a halted RAM PWM test; never reset.

Requires exact backed-up RAM and disabled outputs before writing core debug
registers. No timer/output enable, Flash write, motion or new test is performed.
"""
import argparse
import json
import socket
import subprocess
import time
from pathlib import Path
from pwm_logic_ram_test import ROOT, RAM, RAM_SIZE, TIM1, Tcl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    result = Path(args.result).resolve()
    if not result.is_relative_to((ROOT / "safety_backups").resolve()):
        parser.error("Result must be in workspace safety_backups")
    original = json.loads(result.read_text(encoding="utf-8"))
    context = original["before"]["core"]
    expected_timer = original["before"]["TIM1"]
    assert original["ram_restored"] and original["completed"]
    assert not context["xpsr"] & 0x1FF and 0x08040000 <= context["pc"] < 0x08070000
    backup = (result.parent / "ram-before.bin").read_bytes()
    assert len(backup) == RAM_SIZE
    recovery = {"reset": False, "flash_written": False, "new_pwm_test": False, "resumed": False}
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    cmd = [r"D:\software\xpack-openocd-0.12.0-7\bin\openocd.exe", "-s",
           r"D:\software\openocd-0.12.0\tcl", "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
           "-c", "adapter serial 0050003B3235511537333439", "-c", "adapter speed 1000",
           "-c", "bindto 127.0.0.1", "-c", f"tcl_port {port}", "-c", "gdb_port disabled",
           "-c", "telnet_port disabled", "-c", "init"]
    client = None
    process = None
    with (result.parent / "resume-openocd.log").open("w", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 8
            while True:
                try:
                    client = Tcl(port)
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("OpenOCD unavailable")
                    time.sleep(.05)
            client.command("halt")
            client.command("wait_halt 2000")
            assert client.read(0xE000EDF0)[0] & (1 << 17)
            assert client.read(TIM1, 18) == expected_timer, "Timer settings must already be restored"
            assert not client.read(0x48000814)[0] & 0x40, "SD must be low"
            assert client.read(0xE000ED28)[0] == 0, "No core fault allowed"
            ram = b"".join(word.to_bytes(4, "little") for word in client.read(RAM, RAM_SIZE // 4))
            assert ram == backup, "RAM must already match original backup"
            recovery["halted_before"] = client.core()
            client.restore_core_hardware(context)
            recovery["context_verified"] = client.core() == context
            assert recovery["context_verified"]
            client.command("resume")
            recovery["resumed"] = True
            time.sleep(.2)
            timer = client.read(TIM1, 18)
            gpio = client.read(0x48000814)[0]
            cfsr = client.read(0xE000ED28)[0]
            recovery["after"] = {"TIM1": timer, "GPIOC_ODR": gpio, "CFSR": cfsr}
            assert not timer[0] & 1 and timer[8] == 0 and not timer[17] & 0x8000
            assert not gpio & 0x40 and cfsr == 0
            recovery["pass"] = True
            print("RECOVERY PASS: original core context committed/verified, B resumed; SD=0 MOE=0 CEN=0 CFSR=0; no reset/Flash", flush=True)
        except BaseException as error:
            recovery["error"] = repr(error)
            raise
        finally:
            if client:
                recovery["transcript"] = client.transcript
                try:
                    client.command("shutdown")
                except OSError:
                    pass
                client.socket.close()
            if process:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3)
            (result.parent / "context-recovery.json").write_text(json.dumps(recovery, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
