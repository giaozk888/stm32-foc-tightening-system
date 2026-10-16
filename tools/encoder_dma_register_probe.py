"""Read-only SWD proof of final slot/SAFE/SPI cleanup; no halt, reset or writes."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--expected-slot", choices=("A", "B"), default="B")
    args = parser.parse_args()
    evidence = Path(args.evidence).resolve()
    root = Path(__file__).resolve().parents[1] / "safety_backups"
    if not evidence.is_relative_to(root.resolve()):
        parser.error("Evidence must be inside workspace safety_backups")
    evidence.mkdir(parents=True, exist_ok=True)
    addresses = {
        "VTOR": 0xE000ED08, "CFSR": 0xE000ED28, "NVIC_ISER0": 0xE000E100,
        "GPIOA_ODR": 0x48000014, "GPIOC_ODR": 0x48000814,
        "TIM1_BDTR": 0x40012C44, "DMA4_CCR": 0x40020044,
        "TIM1_CR1": 0x40012C00, "TIM1_CCER": 0x40012C20,
        "DMA5_CCR": 0x40020058, "SPI1_CR2": 0x40013004, "TIM2_DIER": 0x4000000C,
    }
    command = [r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe",
               "-c", "port=SWD", "mode=HOTPLUG", "freq=1000"]
    for address in addresses.values():
        command.extend(("-r32", f"0x{address:08X}", "1"))
    completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    output = completed.stdout + completed.stderr
    matches = {int(a, 16): int(v, 16) for a, v in
               re.findall(r"0x([0-9a-fA-F]{8})\s*:\s*([0-9a-fA-F]{8})", output)}
    values = {name: matches.get(address) for name, address in addresses.items()}
    checks = {}
    if completed.returncode == 0 and all(value is not None for value in values.values()):
        checks = {
            "expected_vector": values["VTOR"] == (0x08008000 if args.expected_slot == "A" else 0x08040000),
            "no_core_fault": values["CFSR"] == 0,
            "rx_irq_restored": bool(values["NVIC_ISER0"] & 0x4000),
            "CS_high": bool(values["GPIOA_ODR"] & 0x10),
            "SD_low": not values["GPIOC_ODR"] & 0x40,
            "MOE_clear": not values["TIM1_BDTR"] & 0x8000,
            "PWM_channels_off": values["TIM1_CCER"] == 0,
            "PWM_timer_stopped": not values["TIM1_CR1"] & 1,
            "DMA4_disabled": not values["DMA4_CCR"] & 1,
            "DMA5_disabled": not values["DMA5_CCR"] & 1,
            "SPI_DMA_requests_off": not values["SPI1_CR2"] & 3,
            "timer_compares_off": not values["TIM2_DIER"] & 0x1E,
        }
    result = {"read_only": True, "registers": values, "checks": checks,
              "pass": bool(checks) and all(checks.values()), "output": output}
    (evidence / "final-registers.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"registers": {name: f"0x{value:08X}" if value is not None else None
                                   for name, value in values.items()},
                      "checks": checks, "pass": result["pass"]}, indent=2))
    if not result["pass"]:
        raise RuntimeError("Final register checks failed")


if __name__ == "__main__":
    main()
