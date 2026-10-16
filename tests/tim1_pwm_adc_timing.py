"""Offline regression for the current TIM1/ADC trigger geometry.

This does not model transistor switching, ADC analog settling, or runtime jitter.
It reads both firmware sources so a changed constant cannot silently inherit an
old timing claim from the chapter notes.
"""

from __future__ import annotations

import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TIMER_HZ = 170_000_000  # HSI 16 MHz / PLLM 4 * PLLN 85 / PLLR 2; APB2 / 1
SCREENING_GUARD_NS = 1_000  # Analysis threshold only; not an ADC hardware requirement.


def number(source: str, pattern: str) -> float:
    match = re.search(pattern, source)
    if match is None:
        raise AssertionError(f"Missing source setting: {pattern}")
    return float(match.group(1))


def settings(slot: str) -> tuple[int, int, float, float, int]:
    source = (ROOT / f"foc2_app_{slot}" / "Core" / "Src" / "main.c").read_text(
        encoding="utf-8"
    )
    for required in (
        "TIM_COUNTERMODE_CENTERALIGNED1",
        "TIM_TRGO2_OC4REF",
        "TIM_OCMODE_PWM2",
        "ADC_EXTERNALTRIGINJEC_T1_TRGO2",
        "ADC_EXTERNALTRIGINJECCONV_EDGE_RISING",
    ):
        assert required in source, (slot, required)

    arr = int(number(source, r"#define\s+PWM_ARR\s+(\d+)U"))
    ccr4 = int(number(source, r"#define\s+ADC_TRIGGER_CCR4\s+(\d+)U"))
    bus = number(source, r"#define\s+FOC_DC_BUS_V\s+([\d.]+)f")
    limit = number(source, r"#define\s+FOC_VOLTAGE_LIMIT_V\s+([\d.]+)f")
    deadtime = int(number(source, r"sBreakDeadTimeConfig\.DeadTime\s*=\s*(\d+);"))
    assert int(number(source, r"htim1\.Init\.Period\s*=\s*(\d+);")) == arr
    assert int(number(source, r"sConfigOC\.OCMode\s*=\s*TIM_OCMODE_PWM2;\s*sConfigOC\.Pulse\s*=\s*(\d+);")) == ccr4
    assert arr > ccr4 > 0 and bus > 0 and limit > 0
    return arr, ccr4, bus, limit, deadtime


def ccr_values(angle: float, amplitude: float, arr: int, bus: float) -> tuple[int, ...]:
    alpha = amplitude * math.cos(angle)
    beta = amplitude * math.sin(angle)
    phases = (
        alpha,
        -0.5 * alpha + math.sqrt(3) * 0.5 * beta,
        -0.5 * alpha - math.sqrt(3) * 0.5 * beta,
    )
    offset = -0.5 * (max(phases) + min(phases))
    duty = [min(0.98, max(0.02, 0.5 + (p + offset) / bus)) for p in phases]
    return tuple(min(arr, int(d * (arr + 1))) for d in duty)


def main() -> None:
    a, b = settings("a"), settings("b")
    assert a == b, f"A/B timing settings differ: A={a}, B={b}"
    arr, ccr4, bus, limit, deadtime = a
    assert deadtime < 128, "DTG left the linear dead-time encoding range"
    assert TIMER_HZ == 170_000_000, "Review clock assumptions before reuse"

    all_ccrs = (
        ccr
        for step in range(3600)
        for ccr in ccr_values(step * 2 * math.pi / 3600, limit, arr, bus)
    )
    max_ccr = max(all_ccrs)
    min_gap_ticks = ccr4 - max_ccr
    guard_ticks = math.ceil(SCREENING_GUARD_NS * TIMER_HZ / 1_000_000_000)
    assert min_gap_ticks > guard_ticks, (
        f"Current FOC duty can approach CH4 trigger: gap={min_gap_ticks} ticks"
    )

    print(f"A/B matched: ARR={arr} CCR4={ccr4} VBUS={bus:g}V limit={limit:g}V")
    print(f"PWM={TIMER_HZ / (2 * arr):.3f}Hz; DTG={deadtime} -> nominal {deadtime / TIMER_HZ * 1e9:.1f}ns")
    print(f"3600-angle sweep: max phase CCR={max_ccr}; closest CH4 gap={min_gap_ticks} ticks = {min_gap_ticks / TIMER_HZ * 1e6:.3f}us")
    print(f"Offline 1us screening margin: >{guard_ticks} ticks: PASS (not analog settling proof)")

    # The generic PWM clamp is wider than the present low-voltage FOC limit.
    # It must not be mistaken for a proven 95% duty/current-sampling envelope.
    near_trigger_duty = ccr4 / (arr + 1)
    assert 0.02 < near_trigger_duty < 0.98
    print(f"WARNING: generic duty {near_trigger_duty * 100:.2f}% maps near CCR4; high duty is NOT validated")

    # A requested 90% is accepted by the generic interface, but at the CH4
    # rising edge the ideal PWM1 reference is still high (CCR1-3 > CCR4).
    # This changes the sampling state. Whether it is usable depends on the
    # actual current-sense topology; digital edge spacing cannot prove it.
    duty_90_ccr = min(arr, int(0.90 * (arr + 1)))
    assert duty_90_ccr == 3825
    print(f"90% request: CCR={duty_90_ccr}; compare after trigger by {(duty_90_ccr - ccr4) / TIMER_HZ * 1e6:.3f}us")
    print("90% at CH4 trigger: ideal PWM1 reference HIGH; not a physical output/ADC validation")

    # Moving duty upward from the current FOC range to 90% passes through the
    # fixed trigger. The 1us band is just an offline review flag, not a safe
    # analog settling specification or a proposed new firmware limit.
    high_duty_steps = range(5000, 9001)
    review_steps = [
        step for step in high_duty_steps
        if abs(int(step / 10000 * (arr + 1)) - ccr4) <= guard_ticks
    ]
    assert review_steps, "Expected a fixed-trigger crossing below 90%"
    print(f"50%-90% sweep, 0.01% steps: compare within 1us screening band at {review_steps[0] / 100:.2f}%-{review_steps[-1] / 100:.2f}%")
    print("RESULT: 90% compare mapping supported; reliable 90% FOC sampling/output NOT established")


if __name__ == "__main__":
    main()
