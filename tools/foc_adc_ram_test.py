"""Bounded digital PWM/ADC SRAM bench. Explicit electrical isolation required.

No Flash, reset, normal startup, motion command, power-stage enable or FOC loop.
Uses the production window/commit/statistics code with a minimal bench IRQ.
The existing ADC1/2 trigger configuration is reused, not reinitialized. Backup
files contain private RAM and must remain local. External logic capture is a
separate measurement; clocks here are checked against the configured timebase.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import time
from pwm_logic_ram_test import Tcl, path_tcl

ROOT = Path(__file__).resolve().parents[1]
RAM, RAM_SIZE = 0x20016000, 0x8000
TIM1, ADC1, ADC2 = 0x40012C00, 0x50000000, 0x50000100
MODES = ["fixed_50", "dynamic_50", "dynamic_80", "dynamic_90", "dynamic_95",
         "dynamic_mixed_95_90_80", "dynamic_updates_2kHz"]
FIELDS = ["index", "mode", "ccr1", "ccr2", "ccr3", "ccr4", "elapsed_us", "elapsed_cycles",
          "irq_entries", "pairs", "pair_misses", "deadline_misses", "max_cycles", "last_cycles",
          "plan_failures", "plan_updates", "blocks", "raw_count", "sum_u", "sum_v", "ss_u", "ss_v",
          "min_u", "min_v", "max_u", "max_v", "step_u", "step_v", "mixed_block", "slack",
          "miss_adc1_flags", "miss_adc2_flags"]

def require_async_adc_clock(adc_ccr, rcc_ccipr):
    """Readback contract: independent ADC1/2, SYSCLK kernel, async /4.

    CKMODE + PRESC + DUAL mask from STM32G474 CMSIS. VREFINT and other
    unrelated bits are not clock selectors and must not cause rejection.
    Frequencies are separately checked against the RCC PLL/bus settings.
    """
    if adc_ccr & 0x003F001F != 0x00080000:
        raise RuntimeError("Independent ADC1/2 with asynchronous /4 required")
    if rcc_ccipr & 0x30000000 != 0x20000000:
        raise RuntimeError("ADC12 kernel must use SYSCLK")


def decode_case(words):
    if len(words) != 32:
        raise ValueError("Incomplete bench case")
    case = dict(zip(FIELDS, words))
    case["name"] = MODES[case["mode"]]
    expected = case["elapsed_us"] * 170 / (2 * 4249)
    case["expected_pairs_from_configured_clock"] = expected
    case["bench_irq_max_us"] = case["max_cycles"] / 170
    case["raw_block_valid_for_stable_comparison"] = case["mixed_block"] == 0 and case["raw_count"] == 256
    for ch in ("u", "v"):
        n = case["raw_count"]
        variance = case[f"ss_{ch}"] / n - (case[f"sum_{ch}"] / n) ** 2 if n else 0
        if variance < -1e-8:
            raise ValueError("Invalid raw sum/square sum")
        case[f"raw_std_{ch}"] = math.sqrt(max(variance, 0))
    case["digital_pass"] = (case["pairs"] == case["irq_entries"] and
        case["pair_misses"] == case["deadline_misses"] == case["plan_failures"] == 0 and
        case["elapsed_us"] >= 100000 and abs(case["pairs"] - expected) <= 3 and case["raw_count"] == 256)
    return case

def build(out):
    arm = Path(r"D:\software\arm\bin")
    app = ROOT / "foc2_app_b"
    elf, binary = out / "foc-adc-ram.elf", out / "foc-adc-ram.bin"
    command = [str(arm / "arm-none-eabi-gcc.exe"), "-mcpu=cortex-m4", "-mthumb", "-mfloat-abi=soft",
               "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Wno-override-init", "-fno-builtin",
               "-ffunction-sections", "-fdata-sections", "-nostdlib", "-nostartfiles",
               "-DSTM32G474xx", "-DUSE_HAL_DRIVER", "-DFOC_ADC_SENSE_TOPOLOGY=2",
               "-DFOC_ADC_SETTLE_TICKS=85", "-Wl,--gc-sections",
               "-T", str(ROOT / "tests/foc_adc_ram_bench.ld")]
    for include in [app / "Core/Inc", app / "Drivers/STM32G4xx_HAL_Driver/Inc",
                    app / "Drivers/CMSIS/Device/ST/STM32G4xx/Include", app / "Drivers/CMSIS/Include",
                    ROOT / "firmware_common"]:
        command.extend(["-I", str(include)])
    command.extend([str(ROOT / "tests/foc_adc_ram_bench.c"),
                    str(ROOT / "firmware_common/foc_adc_window.c"),
                    str(ROOT / "firmware_common/foc_adc_raw_buffer.c"),
                    str(ROOT / "firmware_common/foc_adc_timing_stm32.c"), "-lgcc", "-o", str(elf)])
    completed = subprocess.run(command, capture_output=True, text=True)
    (out / "compile.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError("Bench build failed; see compile.log")
    subprocess.run([str(arm / "arm-none-eabi-objcopy.exe"), "-O", "binary", str(elf), str(binary)], check=True)
    nm = subprocess.check_output([str(arm / "arm-none-eabi-nm.exe"), "-n", str(elf)], text=True)
    symbols = {name: int(address, 16) for address, kind, name in
               re.findall(r"^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$", nm, re.M)}
    assert binary.stat().st_size < RAM_SIZE - 4096
    assert symbols["__bench_bss_end"] < RAM + RAM_SIZE - 4096
    (out / "symbols.json").write_text(json.dumps(symbols, indent=2), encoding="utf-8")
    return binary, symbols

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--permit-isolated-test", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--case-ms", type=int, default=200, choices=range(100, 10001))
    parser.add_argument("--single-95", action="store_true")
    args = parser.parse_args()
    if not (args.permit_isolated_test or args.inspect_only or args.build_only):
        parser.error("Current disconnected-power-stage permission required")
    if not args.single_95 and args.case_ms > 2000:
        parser.error("Seven-case sequence capped at 14 seconds total")
    out = Path(args.evidence).resolve()
    if not out.is_relative_to((ROOT / "safety_backups").resolve()):
        parser.error("Evidence must be inside workspace safety_backups")
    out.mkdir(parents=True, exist_ok=True)
    binary, symbols = build(out)
    if args.build_only:
        print(f"BUILD PASS: RAM-only image {binary.stat().st_size} bytes; 4KB private stack")
        return
    report = {"flash_written": False, "reset": False, "motion_commands": False,
              "power_stage_enabled": False, "foc_loop_executed": False,
              "sensor_topology_confirmed": False, "analog_noise_qualified": False,
              "external_waveform_measured": False, "geometry_test_input": "LOW_SIDE_UV",
              "image_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [ROOT / "tests/foc_adc_ram_bench.c",
                                          ROOT / "firmware_common/foc_adc_window.c",
                                          ROOT / "firmware_common/foc_adc_raw_buffer.c",
                                          ROOT / "firmware_common/foc_adc_timing_stm32.c",
                                          ROOT / "firmware_common/foc_adc_timing_stm32.h",
                                          ROOT / "firmware_common/foc_adc_clock_stm32.h"]},
              "ram_restored": False, "context_restored": False, "pass": False}
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    cmd = [r"D:\software\xpack-openocd-0.12.0-7\bin\openocd.exe", "-s",
           r"D:\software\openocd-0.12.0\tcl", "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
           "-c", "adapter serial 0050003B3235511537333439", "-c", "adapter speed 1000",
           "-c", "bindto 127.0.0.1", "-c", f"tcl_port {port}", "-c", "gdb_port disabled",
           "-c", "telnet_port disabled", "-c", "init"]
    client = process = saved = None
    mutated = ram_loaded = False
    error = None
    try:
        with (out / "openocd.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        end = time.monotonic() + 8
        while True:
            try:
                client = Tcl(port); break
            except OSError:
                if process.poll() is not None or time.monotonic() > end:
                    raise RuntimeError("OpenOCD unavailable")
                time.sleep(.05)
        client.command("halt"); client.command("wait_halt 2000")
        core = client.core()
        assert not core["xpsr"] & 0x1FF, "Must halt in thread context"
        saved = {"core": core, "TIM1": client.read(TIM1, 18), "GPIOC_ODR": client.read(0x48000814)[0],
                 "ADC1": client.read(ADC1, 20), "ADC2": client.read(ADC2, 20),
                 "ADC_CCR": client.read(0x50000308)[0], "TIM2": client.read(0x40000000, 12),
                 "VTOR": client.read(0xE000ED08)[0], "SYSTICK": client.read(0xE000E010, 3),
                 "ISER": client.read(0xE000E100, 4), "ISPR": client.read(0xE000E200, 4),
                 "ICSR": client.read(0xE000ED04)[0], "CFSR": client.read(0xE000ED28)[0],
                 "RCC": client.read(0x40021000, 4), "RCC_CCIPR": client.read(0x40021088)[0],
                 "DWT_CTRL": client.read(0xE0001000)[0],
                 "FPCCR": client.read(0xE000EF34, 2)}
        report["before"] = saved
        t = saved["TIM1"]
        assert not saved["GPIOC_ODR"] & 0x40 and saved["CFSR"] == 0
        assert not t[0] & 1 and t[8] == 0 and not t[17] & 0x8000
        assert t[10] == 0 and t[11] == 4249 and t[12] == 0
        assert t[0] & 0x360 == 0x20 and t[17] & 0xFF == 85
        assert t[6] & 0xFFFF == 0x6868 and t[7] & 0xFFFF == 0x7868
        assert t[1] & 0xF00000 == 0x700000
        assert t[9] < t[16], "Stopped original CH4 must remain inactive when restored"
        assert saved["TIM2"][0] & 1 and saved["TIM2"][10:12] == [169, 0xFFFFFFFF]
        assert saved["DWT_CTRL"] & 1 and not saved["FPCCR"][0] & 1, "No active lazy FPU stacking"
        require_async_adc_clock(saved["ADC_CCR"], saved["RCC_CCIPR"])
        for adc, channel, smp_shift in [(saved["ADC1"], 1, 3), (saved["ADC2"], 2, 6)]:
            assert adc[2] & 0xF == 9, "Existing ADC enabled and injection armed, regular stopped"
            assert adc[3] & 0x80000000 and not adc[3] & 0x2000, "Injected queue disabled, continuous off"
            assert adc[5] >> smp_shift & 7 == 2, "12.5-cycle acquisition required"
            assert adc[19] & 3 == 0 and adc[19] >> 9 & 0x1F == channel
            assert adc[19] >> 7 & 3 == 1, "Rising injected trigger required"
        assert saved["ADC1"][19] & 0x7C == saved["ADC2"][19] & 0x7C
        # HSI16 / M4 * N85 / R2 = 170MHz; AHB/APB prescalers all divide by 1.
        rcc = saved["RCC"]
        assert rcc[2] & 0xC == 0xC and not rcc[2] & 0x3FF0
        assert rcc[3] & 3 == 2 and rcc[3] >> 4 & 0xF == 3 and rcc[3] >> 8 & 0x7F == 85
        assert rcc[3] & (1 << 24) and rcc[3] >> 25 & 3 == 0
        for base, pin, af in [(0x48000800, 1, 2), (0x48000400, 0, 6), (0x48000000, 11, 11)]:
            assert client.read(base)[0] >> (pin * 2) & 3 == 2
            afr = client.read(base + 0x20 + (pin // 8) * 4)[0]
            assert afr >> ((pin % 8) * 4) & 15 == af
        if args.inspect_only:
            report["pass"] = True
            print("INSPECT PASS: original SAFE, PWM off, both ADCs armed for same rising trigger")
        else:
            backup = out / "private-ram-before.bin"
            client.command(f"dump_image {path_tcl(backup)} 0x{RAM:08x} {RAM_SIZE}")
            assert backup.exists() and backup.stat().st_size == RAM_SIZE
            # First mutation is SD RESET, never SET. Then mask old IRQs/SysTick.
            mutated = True
            client.write(0x48000818, 0x00400000)
            client.write(0xE000E010, 0)
            for i in range(4): client.write(0xE000E180 + i * 4, 0xFFFFFFFF)
            client.command(f"load_image {path_tcl(binary)} 0x{RAM:08x} bin"); ram_loaded = True
            image = binary.read_bytes()
            loaded = b"".join(x.to_bytes(4, "little") for x in client.read(RAM, (len(image) + 3) // 4))
            assert loaded[:len(image)] == image
            result = client.command(f"mww 0x{RAM + RAM_SIZE - 4096:08x} 0xa5a5a5a5 1024")
            assert not result and client.read(RAM + RAM_SIZE - 4096)[0] == 0xA5A5A5A5
            client.write(symbols["foc_bench_case_us"], args.case_ms * 1000)
            client.write(symbols["foc_bench_single_95"], int(args.single_95))
            client.write(0xE000ED08, RAM)
            client.write(0xE000E280, 1 << 18)
            client.write(0xE000E100, 1 << 18)
            client.set_core({"msp": RAM + RAM_SIZE, "control": 0, "basepri": 0, "faultmask": 0,
                             "primask": 1, "xpsr": 0x01000000})
            client.command(f"resume 0x{symbols['foc_bench_entry']:08x}")
            deadline = time.monotonic() + args.case_ms / 1000 * (1 if args.single_95 else 7) + 5
            seen = set()
            address = symbols["foc_bench_report"]
            while time.monotonic() < deadline:
                header = client.read(address, 16)
                if header[0] == 0x464F4342:
                    assert not client.read(0x48000814)[0] & 0x40, "SD changed high"
                    if header[1] == 1 and header[2] not in seen:
                        seen.add(header[2])
                        print(f"ADC LOGIC ACTIVE: case {header[2] + 1}/{header[3]}, SD=0; bounded auto-stop", flush=True)
                    if header[1] in (2, 3):
                        client.command("wait_halt 2000")
                        words = client.read(address + 64, 8 * 32)
                        cases = []
                        for idx in range(header[3]):
                            case = decode_case(words[idx * 32:(idx + 1) * 32])
                            cases.append(case)
                            print(f"{case['name']}: pairs/IRQ={case['pairs']}/{case['irq_entries']}, "
                                  f"miss={case['pair_misses']}, CCR4={case['ccr4']}, "
                                  f"bench max={case['bench_irq_max_us']:.3f}us, PASS={case['digital_pass']}", flush=True)
                        report["bench_header"] = header; report["cases"] = cases
                        stack = client.read(RAM + RAM_SIZE - 4096, 1024)
                        free_words = next((i for i, word in enumerate(stack) if word != 0xA5A5A5A5), 1024)
                        report["bench_stack"] = {"reserved_bytes": 4096, "free_canary_bytes": free_words * 4,
                                                 "touched_bytes": (1024 - free_words) * 4,
                                                 "production_foc_stack_qualified": False}
                        assert free_words >= 128, "Bench stack margin below 512 bytes"
                        stopped = client.read(TIM1, 18)
                        assert not stopped[0] & 1 and stopped[8] == 0 and not stopped[17] & 0x8000
                        assert header[1] == 2 and header[5] == header[6] == header[8] == header[9] == 0
                        assert header[10] == header[11] == 0, "Raw statistics backlog drops in bounded bench"
                        report["pass"] = all(c["digital_pass"] for c in cases)
                        break
                time.sleep(.04)
            else:
                raise TimeoutError("Bench did not finish by host deadline")
    except BaseException as exc:
        error = exc; report["error"] = repr(exc)
    finally:
        try:
            if client and saved:
                client.command("halt"); client.command("wait_halt 2000")
                if mutated:
                    client.write(0x48000818, 0x00400000)
                    client.write(TIM1 + 0x44, client.read(TIM1 + 0x44)[0] & ~0x8000)
                    client.write(TIM1 + 0x20, 0)
                    client.write(TIM1, client.read(TIM1)[0] & ~1)
                    client.write(ADC1 + 4, 0); client.write(ADC2 + 4, 0)
                    for i in range(4): client.write(0xE000E180 + i * 4, 0xFFFFFFFF)
                    # Force OC4REF inactive for UG, so restoration cannot trigger ADC.
                    client.write(TIM1 + 0x1C, (saved["TIM1"][7] & ~0x7000) | 0x4000)
                    for off in (0x34, 0x38, 0x3C, 0x40): client.write(TIM1 + off, saved["TIM1"][off // 4])
                    client.write(TIM1 + 0x14, 1)
                    client.write(TIM1 + 0x24, saved["TIM1"][9])
                    for off in (0x1C, 0x04, 0x0C, 0x20, 0x44, 0x00): client.write(TIM1 + off, saved["TIM1"][off // 4])
                    for adc, key in [(ADC1, "ADC1"), (ADC2, "ADC2")]:
                        client.write(adc, 0x60)
                        client.write(adc + 4, saved[key][1])
                    for i in range(4):
                        client.write(0xE000E280 + i * 4, 0xFFFFFFFF)
                        client.write(0xE000E200 + i * 4, saved["ISPR"][i])
                    client.write(0xE000ED08, saved["VTOR"])
                    # Restore PendSV/SysTick pending state; pause time is not RTOS wall time.
                    client.write(0xE000ED04, (1 << 27) | (1 << 25))
                    client.write(0xE000ED04, saved["ICSR"] & ((1 << 28) | (1 << 26)))
                    for i in range(4): client.write(0xE000E100 + i * 4, saved["ISER"][i])
                    client.write(0xE000E014, saved["SYSTICK"][1])
                    client.write(0xE000E018, 0)  # Restart tick phase, not elapsed wall-clock compensation.
                    client.write(0xE000E010, saved["SYSTICK"][0] & 7)
                if ram_loaded:
                    backup = out / "private-ram-before.bin"
                    client.command(f"load_image {path_tcl(backup)} 0x{RAM:08x} bin")
                    restored = b"".join(x.to_bytes(4, "little") for x in client.read(RAM, RAM_SIZE // 4))
                    report["ram_restored"] = restored == backup.read_bytes()
                    assert report["ram_restored"], "RAM restoration failed; leave halted"
                client.restore_core_hardware(saved["core"])
                report["context_restored"] = client.core() == saved["core"]
                assert report["context_restored"]
                assert client.read(0xE000EF34, 2) == saved["FPCCR"], "FPU context changed; leave halted"
                assert client.read(0xE000ED28)[0] == 0, "Core fault; leave halted"
                client.command("resume"); time.sleep(.1)
                after = {"TIM1": client.read(TIM1, 18), "GPIOC_ODR": client.read(0x48000814)[0],
                         "CFSR": client.read(0xE000ED28)[0], "VTOR": client.read(0xE000ED08)[0]}
                report["after"] = after
                assert not after["GPIOC_ODR"] & 0x40 and after["CFSR"] == 0 and after["VTOR"] == saved["VTOR"]
                assert not after["TIM1"][0] & 1 and after["TIM1"][8] == 0 and not after["TIM1"][17] & 0x8000
                print("RESTORE PASS: original SAFE resumed, SD=0 MOE=0; no Flash/reset", flush=True)
        except BaseException as cleanup_error:
            error = cleanup_error; report["cleanup_error"] = repr(cleanup_error)
            report["pass"] = False
            print(f"RESTORE ERROR: {cleanup_error}; keep power stage disconnected, do not reset", flush=True)
        if client:
            # Transcript can include private RAM. Do not echo it or share backups.
            (out / "private-transcript.json").write_text(json.dumps(client.transcript), encoding="utf-8")
            try: client.command("shutdown")
            except OSError: pass
            client.socket.close()
        if process:
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=3)
        (out / "foc-adc-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if error: raise error
    if not report["pass"]: raise RuntimeError("Bench not accepted; inspect measured cases")

if __name__ == "__main__": main()
