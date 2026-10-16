"""Isolated, bounded CH2/CH2N logic-only test. No Flash, reset or motion.

Requires physically disconnected power stage, independent MCU supply and
explicit user permission. Runs a tiny stackless Thumb routine in backed-up
SRAM while the normal SAFE firmware is paused. Restores SRAM, core context
and TIM1 settings before resuming. A hardware capture is still required;
register checks alone are not a measured waveform or FOC qualification.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAM = 0x20016000
RAM_SIZE = 1024
RESULT = RAM + 768
TIM1 = 0x40012C00
REGS = [f"r{i}" for i in range(13)] + ["lr", "pc", "xpsr", "primask", "msp", "psp", "control", "basepri", "faultmask"]


class Tcl:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.socket.settimeout(8)
        self.transcript = []

    def command(self, command):
        # Only these operations are used; no Flash, reset, erase or GPIO SET.
        self.socket.sendall(command.encode() + b"\x1a")
        data = bytearray()
        while not data.endswith(b"\x1a"):
            block = self.socket.recv(65536)
            if not block:
                raise RuntimeError("OpenOCD disconnected")
            data.extend(block)
        result = data[:-1].decode(errors="replace").strip()
        self.transcript.append({"command": command, "result": result})
        return result

    def read(self, address, count=1):
        result = self.command(f"read_memory 0x{address:08x} 32 {count}")
        try:
            values = [int(item, 0) for item in result.split()]
        except ValueError as error:
            raise RuntimeError(f"Memory read failed: {result}") from error
        if len(values) != count:
            raise RuntimeError(f"Memory read length mismatch: {result}")
        return values

    def write(self, address, value):
        result = self.command(f"mww 0x{address:08x} 0x{value:08x}")
        if result:
            raise RuntimeError(f"Register write failed: {result}")

    def core(self):
        # Force the hidden 32-bit special-register container first: OpenOCD's
        # force read of PRIMASK/CONTROL alone can reuse this stale container.
        self.command("get_reg -force {pmsk_bpri_fltmsk_ctrl}")
        result = self.command("get_reg -force {" + " ".join(REGS) + "}")
        pairs = re.findall(r"(\w+)\s+(0x[0-9a-fA-F]+)", result)
        values = {key: int(value, 16) for key, value in pairs}
        if set(values) != set(REGS):
            raise RuntimeError(f"Incomplete core context: {result}")
        return values

    def set_core(self, values):
        result = self.command("set_reg {" + " ".join(f"{key} 0x{value:08x}" for key, value in values.items()) + "}")
        if result:
            raise RuntimeError(f"Core restore failed: {result}")

    def restore_core_hardware(self, values):
        # OpenOCD set_reg updates a dirty cache which is committed on resume.
        # A force read before resume discards those pending cache writes!
        # Commit directly through Cortex-M DCRDR/DCRSR while halted, verify
        # S_REGRDY, then force-refresh OpenOCD's cache from the real core.
        assert self.read(0xE000EDF0)[0] & (1 << 17), "Core must be halted"
        indices = {f"r{i}": i for i in range(13)}
        indices.update({"lr": 14, "pc": 15, "xpsr": 16, "msp": 17, "psp": 18})
        writes = [(index, values[name]) for name, index in indices.items()]
        special = ((values["control"] & 0xFF) << 24 | (values["faultmask"] & 0xFF) << 16 |
                   (values["basepri"] & 0xFF) << 8 | (values["primask"] & 0xFF))
        writes.append((20, special))
        for index, value in writes:
            self.write(0xE000EDF8, value)
            self.write(0xE000EDF4, 0x10000 | index)
            deadline = time.monotonic() + 1
            while not self.read(0xE000EDF0)[0] & (1 << 16):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Core register {index} commit timed out")
        if self.core() != values:
            raise RuntimeError("Hardware core context readback mismatch")


def path_tcl(path):
    # Paths are workspace-controlled, never shell expanded.
    value = str(path.resolve()).replace("\\", "/")
    if any(char in value for char in '{}\n\r'):
        raise ValueError("Unsafe Tcl path")
    return "{" + value + "}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--seconds", type=int, choices=range(5, 21), default=20)
    parser.add_argument("--ccr2", type=int, choices=(3825, 3867), default=3867,
                        help="3825: raw 90%% command; 3867: ~90%% pin duty after nominal 85-tick deadtime")
    parser.add_argument("--permit-logic-test", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    if not args.inspect_only and not args.permit_logic_test:
        parser.error("Explicit disconnected-power-stage logic-test permission required")
    evidence = Path(args.evidence).resolve()
    if not evidence.is_relative_to((ROOT / "safety_backups").resolve()):
        parser.error("Evidence must be inside workspace safety_backups")
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"flash_written": False, "reset": False, "motion_commands": False,
              "inspect_only": args.inspect_only, "seconds": args.seconds, "CCR2": args.ccr2,
              "ram_restored": False, "context_restored": False, "completed": False}
    compiler = r"D:\software\arm\bin\arm-none-eabi-gcc.exe"
    objcopy = r"D:\software\arm\bin\arm-none-eabi-objcopy.exe"
    elf = evidence / "pwm-logic-ram.elf"
    binary = evidence / "pwm-logic-ram.bin"
    subprocess.run([compiler, "-mcpu=cortex-m4", "-mthumb", "-nostdlib", "-nostartfiles",
                    "-Wl,-Ttext=0x20016000", "-Wl,--entry=pwm_logic_entry",
                    str(ROOT / "tests" / "pwm_logic_ram.S"), "-o", str(elf)], check=True)
    subprocess.run([objcopy, "-O", "binary", str(elf), str(binary)], check=True)
    if binary.stat().st_size > 512:
        raise RuntimeError("RAM routine exceeds reserved code area")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    openocd = r"D:\software\xpack-openocd-0.12.0-7\bin\openocd.exe"
    scripts = r"D:\software\openocd-0.12.0\tcl"
    command = [openocd, "-s", scripts, "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
               "-c", "adapter serial 0050003B3235511537333439", "-c", "adapter speed 1000",
               "-c", "bindto 127.0.0.1", "-c", f"tcl_port {port}", "-c", "gdb_port disabled",
               "-c", "telnet_port disabled", "-c", "init"]
    client = None
    saved_core = None
    timer = None
    ram_loaded = False
    backed_up = False
    halted = False
    test_started = False
    process = None
    error = None
    with (evidence / "openocd.log").open("w", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 8
            while True:
                try:
                    client = Tcl(port)
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("OpenOCD unavailable; inspect openocd.log")
                    time.sleep(.05)
            client.command("halt")
            client.command("wait_halt 2000")
            halted = True
            saved_core = client.core()
            if saved_core["xpsr"] & 0x1FF:
                raise RuntimeError("Halted in exception context; no test mutation permitted")
            timer = client.read(TIM1, 18)
            gpio = client.read(0x48000814)[0]
            tim2 = client.read(0x40000000, 12)
            dwt = client.read(0xE0001000)[0]
            report["before"] = {"core": saved_core, "TIM1": timer, "GPIOC_ODR": gpio, "TIM2": tim2, "DWT_CTRL": dwt}
            assert not gpio & 0x40, "SD must already be low"
            assert not timer[0] & 1 and timer[8] == 0 and not timer[17] & 0x8000, "PWM must be off"
            assert timer[10] == 0 and timer[11] == 4249 and timer[12] == 0, "Unexpected PWM timebase"
            assert timer[6] & 0xFF00 == 0x6800 and timer[17] & 0xFF == 85, "Unexpected PWM1/deadtime"
            assert timer[1] & 0xF00000 == 0x700000 and timer[7] & 0xFF00 == 0x7800, "Expected CH4 PWM2 -> TRGO2 OC4REF"
            assert timer[9] < timer[16], "Restoring stopped CH4 must not raise OC4REF"
            assert tim2[0] & 1 and tim2[10] == 169 and tim2[11] == 0xFFFFFFFF, "TIM2 must be existing 1MHz free-run"
            assert dwt & 1, "DWT cycle fallback must already be enabled"
            moder_c = client.read(0x48000800)[0]
            moder_b = client.read(0x48000400)[0]
            af_c = client.read(0x48000820)[0]
            af_b = client.read(0x48000420)[0]
            assert (moder_c >> 2) & 3 == 2 and (af_c >> 4) & 15 == 2, "PC1 must be TIM1 AF2"
            assert moder_b & 3 == 2 and af_b & 15 == 6, "PB0 must be TIM1 AF6"
            if args.inspect_only:
                report["completed"] = True
                print("INSPECT PASS: outputs off; timebases and PC1/PB0 alternate functions match", flush=True)
            else:
                backup = evidence / "ram-before.bin"
                result = client.command(f"dump_image {path_tcl(backup)} 0x{RAM:08x} {RAM_SIZE}")
                if not backup.exists() or backup.stat().st_size != RAM_SIZE:
                    raise RuntimeError(f"RAM backup failed: {result}")
                backed_up = True
                result = client.command(f"load_image {path_tcl(binary)} 0x{RAM:08x} bin")
                ram_loaded = True
                # Compare bytes as words, not merely the debugger's load message.
                image = binary.read_bytes()
                words = client.read(RAM, (len(image) + 3) // 4)
                loaded = b"".join(word.to_bytes(4, "little") for word in words)
                if loaded[:len(image)] != image:
                    raise RuntimeError(f"RAM routine readback mismatch: {result}")
                client.write(RESULT, 0)
                client.write(RESULT + 4, 0)
                client.write(RESULT + 8, 0)
                # MMS2=RESET would pulse TRGO2 on EGR.UG! Instead keep OC4REF
                # selected and force CH4 inactive, including during preload UG.
                client.write(TIM1 + 0x1C, (timer[7] & ~0x7000) | 0x4000)
                client.write(TIM1 + 0x0C, 0)       # No timer interrupts/DMA requests.
                client.write(TIM1 + 0x38, args.ccr2)  # Isolated waveform setting, not normal FOC.
                client.write(TIM1 + 0x14, 1)       # Load preloads while OC4REF/TRGO2 stays low.
                client.write(TIM1 + 0x24, 0)
                client.write(TIM1 + 0x20, 0x50)    # CH2 + CH2N only, active high.
                client.set_core({"primask": 1, "r8": args.seconds * 1_000_000,
                                 "r9": (args.seconds + 2) * 170_000_000, "r10": RESULT})
                test_started = True
                client.command(f"resume 0x{RAM:08x}")
                halted = False
                deadline = time.monotonic() + args.seconds + 5
                active_seen = False
                while time.monotonic() < deadline:
                    status = client.read(RESULT, 3)
                    if status[0] == 1 and not active_seen:
                        live_timer = client.read(TIM1, 18)
                        live_gpio = client.read(0x48000814)[0]
                        assert live_timer[0] & 1 and live_timer[8] == 0x50 and live_timer[14] == args.ccr2
                        assert live_timer[17] & 0x8000 and not live_gpio & 0x40
                        report["during"] = {"TIM1": live_timer, "GPIOC_ODR": live_gpio}
                        active_seen = True
                        print(f"PWM LOGIC ACTIVE: PC1/PB0, CCR2={args.ccr2}, SD=0, auto-stop <= {args.seconds + 2}s. Capture now.", flush=True)
                    if status[0] == 2:
                        report["routine_result"] = {"state": status[0], "elapsed_us": status[1], "elapsed_cycles": status[2]}
                        client.command("wait_halt 2000")
                        halted = True
                        stopped = client.read(TIM1, 18)
                        assert not stopped[0] & 1 and stopped[8] == 0 and not stopped[17] & 0x8000
                        assert not client.read(0x48000814)[0] & 0x40
                        report["completed"] = active_seen
                        print("PWM AUTO-STOP PASS: SD=0 MOE=0 CCER=0 CEN=0", flush=True)
                        break
                    time.sleep(.1)
                else:
                    raise TimeoutError("RAM routine did not stop by host deadline")
        except BaseException as exception:
            error = exception
            report["error"] = repr(exception)
        finally:
            try:
                if client and saved_core:
                    if not halted:
                        client.command("halt")
                        client.command("wait_halt 2000")
                        halted = True
                    if test_started or ram_loaded:
                        client.write(0x48000818, 0x00400000)  # Reset SD, never SET.
                        client.write(TIM1 + 0x44, client.read(TIM1 + 0x44)[0] & ~0x8000)
                        client.write(TIM1 + 0x20, 0)
                        client.write(TIM1, client.read(TIM1)[0] & ~1)
                        client.write(TIM1 + 0x38, timer[14])
                        client.write(TIM1 + 0x1C, (timer[7] & ~0x7000) | 0x4000)
                        client.write(TIM1 + 0x14, 1)
                        client.write(TIM1 + 0x24, timer[9])
                        for offset in (0x1C, 0x04, 0x0C, 0x20, 0x44, 0x00):
                            client.write(TIM1 + offset, timer[offset // 4])
                    if backed_up and ram_loaded:
                        client.command(f"load_image {path_tcl(evidence / 'ram-before.bin')} 0x{RAM:08x} bin")
                        restored = b"".join(word.to_bytes(4, "little") for word in client.read(RAM, RAM_SIZE // 4))
                        report["ram_restored"] = restored == (evidence / "ram-before.bin").read_bytes()
                        if not report["ram_restored"]:
                            raise RuntimeError("RAM restore failed; CPU left halted with outputs off")
                    client.restore_core_hardware(saved_core)
                    report["context_restored"] = client.core() == saved_core
                    if not report["context_restored"]:
                        raise RuntimeError("Core restore failed; CPU left halted with outputs off")
                    client.command("resume")
                    halted = False
                    time.sleep(.1)
                    report["after"] = {"TIM1": client.read(TIM1, 18), "GPIOC_ODR": client.read(0x48000814)[0],
                                       "CFSR": client.read(0xE000ED28)[0]}
                    assert not report["after"]["TIM1"][0] & 1
                    assert not report["after"]["TIM1"][17] & 0x8000
                    assert report["after"]["TIM1"][8] == 0
                    assert not report["after"]["GPIOC_ODR"] & 0x40
                    assert report["after"]["CFSR"] == 0
                    print("RESTORE PASS: original firmware resumed, all outputs off; no Flash/reset", flush=True)
            except BaseException as cleanup_error:
                report["cleanup_error"] = repr(cleanup_error)
                error = cleanup_error
                print(f"RESTORE ERROR: {cleanup_error}. Do not reset or reconnect power stage.", flush=True)
            if client:
                report["transcript"] = client.transcript
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
            (evidence / "pwm-logic-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if error:
        raise error
    if not report["completed"]:
        raise RuntimeError("Test did not establish active/stopped states")


if __name__ == "__main__":
    main()
