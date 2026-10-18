# Current-feedback polarity comparison (2026-10-17)

## Status

Implemented and offline-tested an explicit CONTROL-feedback polarity selection.
This is a diagnostic preparation, NOT a confirmed repair of motor overspeed.
The physical sign/phase mapping remains unproven. No board access, Flash write,
reset, boot-selection change, motor start or automatic retry was performed.

The Genbotter manual (Desktop copy, physical PDF pages 7 and 9, figures 2-4
and 2-6) shows low-side shunts and a positive shunt-voltage amplifier gain
of 120 mV/A. Shunt-current sign and current flowing OUT of the inverter phase
are not automatically the same convention. The formula alone does not justify
reversing the production phase-current feedback. Both relevant pages were
rendered and visually inspected using the PDF workflow.

## Changes

- `firmware_common/foc_current_feedback_polarity.h`: one compile-time conversion
  helper, no runtime branch/configuration, no allocation, no I/O. Default
  `FOC_CURRENT_FEEDBACK_SIGN=-1` gives the exact existing `(zero-raw)*scale`.
  `+1` gives `(raw-zero)*scale` for a power-hard-off comparison only.
- `foc_feedback_safety_candidate.h`: the active fast-reject valid-frame path
  calls that helper for U and V. U/V are not swapped; W is still `-(U+V)`.
- A/B CMake validates -1/+1 and propagates the definition. A positive-sign
  configuration without `FOC_FAST_REJECT_COMPUTE_ONLY=1` is rejected by CMake
  AND by the C header. No host-only backdoor was added.
- A/B preset `CurrentPolarityComputeOnly` inherits `EncoderFocFirst` (one-cycle
  pending PWM and existing IRQ arrangement), keeps bridge-enable transactions
  compiled out, and uses light profiling with sign +1.
- Added synthetic host regression tests. No current validator, CUR_CONFIRM,
  raw overcurrent policy/threshold, PI gain/math, SVPWM, PWM pipeline, encoder
  direction/zero/pole pairs, tightening FSM, or A/B boot logic was changed.

Raw protection counts and binary fault-trace counts intentionally remain
`zero-raw`; they are NOT reinterpreted as the candidate's signed dq feedback.
The existing protection observes the same physical ADC pairs, with unchanged
phase/W absolute-value tests. Do not compare a reverse candidate's dq sign to
raw trace counts without applying the explicit control-feedback sign.

## Builds

Separate directories preserve all pinned images:
`foc2_app_{a,b}/build/CurrentPolarityReview/{Formal,ReverseHardOff}`.

| Slot/profile | Flash bytes | RAM bytes | Result |
|---|---:|---:|---|
| A Formal (-1) | 228940 | 127944 | linked |
| B Formal (-1) | 227924 | 127928 | linked |
| A ReverseHardOff (+1) | 226116 | 127104 | linked |
| B ReverseHardOff (+1) | 225100 | 127088 | linked |

Both formal BINs are byte-identical to their existing RollingTraceBaseline
images. A SHA256: `b4d2368220699e6cf792b0a7032c52e3c74cb112351133363f97bcc4706cdd3e`.
B SHA256: `4dad58d581755072d15a36da0492a809df2735dc654203f7b3e8a98b77b27ec8`.
The default helper's isolated Cortex-M4 machine code is also identical to the
old conversion. Therefore this is not a claim that the formal motor behavior
has already changed or that a 50 us board test was rerun.

A ReverseHardOff BIN SHA256:
`a1dc3b493dcbfb7a52b955d350a10626db11835d1f9022fdff4a868d241f9322`.
B ReverseHardOff BIN SHA256:
`1414d15686290feded880fea9cba30b62c8e3772585ac452dba9905ce4dfaff9`.

Existing source unused-function/variable and RWX LOAD-segment warnings remain;
there were no build errors. Strict new host tests use -Wall/-Wextra/-Werror.
The existing integrated source-warning comparison also passed. No attempt was
made to silence unrelated warnings or rewrite linker sections.

## Offline validation

28 unittest methods passed in these suites:

- `test_current_feedback_polarity`: 3 (both signs at -Os/-O2, unchanged raw
  protection including reconstructed W, unchanged suspect/unresolved fault,
  zero/full-scale arithmetic, default ARM machine-code equivalence, invalid
  sign and actuating reverse-sign compile rejection).
- `test_foc_cur_confirm_cycles`: 2.
- `test_foc_fast_current_reject`: 8.
- `test_pipeline_closed_loop`: 6 (including the original FSM/pending pipeline,
  actual mock CCR adapter and existing historical-image checks).
- `test_current_fault_trace`: 9.

Independent CMake checks rejected A's attempted actuating +1 configuration and
B's invalid zero-sign configuration as intended. These expected rejections are
not failed usable firmware builds.

## What remains before an actual correction

The saved startup history implicates current-feedback tracking before overspeed,
but does not uniquely distinguish sensor sign, physical phase correspondence,
driver-input polarity or analog sampling validity. Output-off arithmetic
comparison cannot identify the physical plant sign. A controlled physical
polarity/phase-mapping check is still required before selecting a new actuating
sign; do not use a successful synthetic test as evidence that the motor is fixed.
