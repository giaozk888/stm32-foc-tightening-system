# Zero calibration: bounded valid-sample admission

Subsequent board verification: see [two real startup calibrations](zero-valid-admission-board-20261018.md).
The offline-only statements below describe the implementation turn, before
that separately authorized board run.

## Scope and activation

This change only affects startup zero sample admission and its foreground
diagnostics. `ZeroValidAdmissionTrial` is available in both app directories and
inherits `SpeedStartupBrakeTrial`. The new option `FOC_ZERO_VALID_ADMISSION` is
opt-in so historical images and their evidence remain reproducible. Use the new
preset, not an old SpeedStartupBrakeTrial image, to test this change.

No board access, flashing, START, reset, or boot-selection change was performed.
The new speed-loop parameters, runtime current discriminator, CUR_CONFIRM,
CURRENT_INVALID, hard-overcurrent, one-cycle PWM pipeline, PI and SVPWM are not
changed by this work.

## Previous failure and new behavior

The old five-pair estimator set `FOC_ROBUST_BURST` when more than one physical
pair differed from either channel's own median by more than 40 ADC counts. It
then immediately called `FocZero_Abort`, losing the complete 4000-pair attempt.

The observed failure at 3120/4000 has this next block:

| Pair | IU | IV | Admitted |
|---|---:|---:|---|
| 1 | 1564 | 1570 | yes |
| 2 | 1535 | 1526 | no: IV differs from median by 44 |
| 3 | 1565 | 1570 | yes |
| 4 | 1625 | 1646 | no: differences 61 / 76 |
| 5 | 1561 | 1567 | yes |

Medians remain 1564/1570. The new policy admits three actual raw pairs,
rejects two whole pairs, stays COLLECTING, and replenishes the missing pairs.
This exact block is a fixed regression case; it does not claim that the full
historical capture was replayed.

Each five-pair block uses the existing median and >40-count predicate.
Rejected pairs never enter either channel's sum, first-half sum, or segment
sum. `FocZeroCal.count` now counts accepted physical pairs in this profile.
READY requires exactly 4000 accepted pairs, with rounded accepted-only means.
The eight drift segments now contain 500 accepted pairs each; the segment
mean difference limit remains five counts (sum scaling adjusted accordingly).

## Finite limits

Macros are in `firmware_common/foc_zero_valid_admission.h`:

| Limit | Value | Failure condition |
|---|---:|---|
| ZERO_CAL_VALID_TARGET | 4000 | Never READY before this accepted count |
| ZERO_CAL_MAX_TOTAL_SAMPLES | 4100 | Reached without 4000 accepted pairs |
| ZERO_CAL_MAX_REJECT_COUNT | 80 | Reject 81 |
| ZERO_CAL_MAX_CONSEC_REJECT | 2 | Consecutive reject 3, including across blocks |

The observed cumulative count was 43 rejects / 3125 physical collection pairs
(1.376%). This suggests about 55 rejects per 4000 valid pairs. The provisional
80-reject allowance is about 2% of the valid target, not an unlimited mask.
4100 is a bounded 2.5% physical collection allowance. These are startup sample
budgets, not changed current thresholds or an electrical safety certification.

The original 20000-pair settling interval and 5-second timeout remain. Collection
`total_count` excludes settling. It counts physical arrivals; because the median
requires five samples, the final successful block may have up to four buffered
but unused tail pairs. Thus final `total_count - valid_count - reject_count`
can be 0..4. No tail values enter offset sums. Failed blocks can similarly
retain unprocessed tail pairs in physical arrival diagnostics.

The existing immediate invalid-ADC check (>4095), nominal/median range,
100-count nominal displacement and center-span gates, and five-count segment
drift gate remain. Two inliers each within 40 counts of one median have at most
80-count separation, satisfying the unchanged 100-count within-block bound.
The final mean also must remain within the existing nominal displacement gate.
Runtime safety and hardware shutoff paths are not part of sample admission.

## Diagnostics and size

StartupTask emits `ZERO CAL` after its calibration wait, never in the ADC ISR.
The same formatter serves `MOTOR TEST ZERO` and `MOTOR TEST ZERO ROBUST`:

`valid`, `reject`, `total`, `reject_rate_ppt`, `max_consecutive_reject`,
`zero_u`, `zero_v`, `result`, `STATE`, `REASON`, `FLAGS`.

`reject_rate_ppt` is an integer per-thousand ratio of rejected / physical
collection pairs. `result=1` means READY; 0 means not READY. Numeric STATE,
REASON and FLAGS distinguish incomplete and failed results.

To retain A-slot headroom, only the new zero estimator is compiled with `-Os`.
The redundant raw-only contrast estimator is not run in this profile; it never
owned a safety decision. Raw min/max/outside-nominal diagnostics and the real
protected binding checks remain. The formatter is shared, cold, and size
optimized. No runtime current-loop function received an optimization change.

| Build preset | Flash bytes / 229376 | RAM region bytes / 131008 |
|---|---:|---:|
| A ZeroValidAdmissionTrial | 228428 | 127960 |
| B ZeroValidAdmissionTrial | 227412 | 127944 |

A has 948 bytes of Flash headroom; B has 1964. Compiler warning comparison
against SpeedStartupBrakeTrial found no new warnings. Existing unused-function/
unused-variable and linker RWX warnings remain; they were not suppressed.

## Offline verification

`python -m unittest discover -s tests -p test_zero_valid_admission.py -v`
passes all 12 tests. Actual C runs at `-Os` and `-O2` cover 4000 normal pairs,
isolated spikes, the real two-spike block, cross-block consecutive rejection,
80/81 rejection boundaries, accepted-only sums in BOTH channels, an independent
total limit, original invalid/shift/drift failures, terminal-state immutability,
actual protected binding and foreground diagnostics, profile inheritance, and
ARM warning comparison. Binding failure still reaches CL_BAD_ZERO with outputs
off. These are software/register-mock results, not board or torque validation.

Full existing discovery was also run: 1114 tests, 1101 passed, 9 failures and
4 errors. It is NOT all green. The original full discovery collected the first
10 new tests; the final focused run separately includes all 12 tests.

Unrelated failing historical checks are retained without weakening assertions:

- control_chain_reconnect: legacy extracted current-loop fixture does not compile;
- current_fault_trace_board_test: private historical baseline file read denied;
- current_impulse_board_test and timeout_diagnostics_board_test: pinned historical
  image identity/size does not match available artifacts;
- feedback_safety_binding: old source-distance assertion;
- foc_feedback_fast and foc_guard_fast: old literal TIM7-priority assertion;
- foc_path_profile: historical protection-source hash pin;
- foc_repair_trace: old source substring/freeze-layout assertion;
- protected_irq_optimized: old dispatcher source-layout assertion;
- rc_deferred_shadow: old bridge admission source assertion;
- tighten_synthetic_acceptance (two tests): historical main/startup baseline differs.

Logs: `tmp/zero-admission-focused-tests.log`,
`tmp/zero-admission-all-tests.log`, and A/B build logs under `tmp/`.
No unrelated control changes, historical pin updates, board actions, or
protection-threshold changes were made to hide these failures.

zero-calibration robust sample admission 已完成，等待人工上板重复校准验证
