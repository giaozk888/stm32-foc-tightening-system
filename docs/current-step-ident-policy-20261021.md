# Reuse identification encoder policy in the current-step candidate

Status: file-only `CurrentStepAbIdentPolicy` candidate A prepared and compiled;
NOT flashed, no motor/current command, no boot-selection change this turn.
Board remains at the previously restored/ halted B900 entry (driver12V OFF
was confirmed at the end of the last experiment).

## Finding: earlier identification fixes were not inherited

`CurrentStepAbGateEvidence` and original step A both had
`AS5047P_DMA_TERMINAL_FIX=OFF` and `AS5047P_DMA_TIMING_POLICY_V2=OFF`.
The identification experiment had already enabled those two opt-in policies.
This is a concrete configuration mismatch, not proof that every protection
threshold is unnecessary.

Re-decoding the three exact-image saved attempts also showed:

| Attempt | First CL flags | Encoder elapsed/budget | Driver fault time | CL off time |
|---|---:|---:|---:|---:|
|1792570483711951500|16|201/200us|7953513|7953522|
|1792572252465902700|16|215/200us|7962549|7962545|
|1792573490563630600|32|201/200us|7933900|7933905|

The driver event top-half can close SD/MOE before its lower-priority fault
publication. An ADC/guardian gate check in that interval could label the
result BAD_OUTPUT before the encoder fault is published. This is a plausible
code/timestamp explanation for different first labels, NOT captured proof of
the exact writer/interrupt interleaving in the two older attempts. Preserve
the pre-closure evidence probe to distinguish it during future testing.

## What is reused, and what is not

Only the existing identification encoder terminal arbitration and policy V2
are enabled in a separate, explicitly guarded step preset:

| Contract | Old step | New diagnostic A |
|---|---:|---:|
| terminal completion arbitration before cleanup |OFF|ON|
| slow completed transaction warning |not separately counted|>=200us|
| incomplete transaction hard deadline |200us|400us|
| schedule lateness stop |200us|200us|
| encoder period |1000us|1000us|
| maximum sample age |1500us|1500us|
| control watchdog |2500us|2500us|
| FOC deadline |50us|50us|

This **does change the diagnostic encoder transaction cutoff200→400us**.
It does NOT cancel timeout protection, mark an incomplete/parity-invalid
transaction successful, backdate completion, refresh a stale sample, or
change IRQ priority/frequency. It reuses the existing driver implementation;
no new engine/deferred algorithm is copied or invented.

The hardware/current/output/discriminator/CUR_CONFIRM/PI/PWM pipeline paths
and independent stops remain unchanged. Default formal A/B remain OFF for
these new selection flags; CMake refuses enabling the step adaptation without
exclusive step mode, gate evidence, terminal fix and policy V2 together.

Current-step capture already operates only on accepted current pairs, counts
skipped sequences and does not have an Rs-style cumulative-rejection stop.
Regression now also checks100 skipped pairs do not themselves abort and an
actual protection fault still does. Missing samples are never interpolated;
metrics with insufficient/gapped observations must not claim a proven A/B
rise/settling improvement. Positive-quality gate before negative pulses stays.
The Rs-only0.20A estimator admission is intentionally NOT copied: applying it
to this test would discard legitimate0.30A step response.

## New foreground command

`MOTOR TEST CURRENT STEP ENCODER TIME`

Returns POLICY2, TERMINAL_FIX1, WARN_US200, DEADLINE_US400, SCHED_US200,
PERIOD_US1000, AGE_US1500, CONTROL_US2500, SLOW_N and OK_MAX_US.
SLOW_N/OK_MAX_US are successful-transaction statistics accumulated since boot,
not proof of a single batch's peak. Read SLOW_N before/after to get its delta.
Formatting is foreground-only; no new ISR printf/UART.

## Files/build/test

Changed `foc2_app_a/CMakeLists.txt`, `foc2_app_a/CMakePresets.json`,
`firmware_common/current_step_ab_binding.inc`.
Added `tests/test_current_step_ident_policy.py` and this document.
Driver, current-step kernel, controller and stable B sources are not changed.

| Build | Flash B | RAM B | Result |
|---|---:|---:|---|
|CurrentStepAbIdentPolicy A|214340|129872|PASS|
|Normal identified-PI A, isolated rebuild|217428|129160|PASS, BIN unchanged|
|Stable B, isolated rebuild|228300|128792|PASS, BIN unchanged|

New BIN SHA256 `20398c4906f1b1a6ba1fc6902cde68c0e1988fd0b64f6e091ff885c22e48f9d1`.
New ELF SHA256 `5db4b36d06688ecc30fc0a011625be2d3a6245adf9f02f63f991df4bc4d0776e`.

35 relevant offline tests PASS: step policy5, existing terminal arbitration2,
existing encoder timing4, step/kernel/transport12, gate evidence5,
CUR_CONFIRM2, current PI5. No new warnings in actual main/driver comparison;
existing unused-function/variable and RWX linker warnings remain.
Observed WORD/frame1 delayed completion at201us is covered with the actual
driver top/bottom halves and engine at -Os/-O2; incomplete400 still forces OFF.
Normal A/B/earlier diagnostic BIN hashes remain unchanged. Runtime timing and
success of the new board test are NOT claimed without a new measurement.

## Next manual board test

Keep normal OFF stage / exact full readback / separate ON acknowledgement /
one bounded protected batch / OFF B-restore workflow. The existing board
runners deliberately remain pinned to their previous images and must NOT
silently flash this new one. Bind the new exact BIN/ELF and policy readback
before a future explicitly requested trial. Start from the validated B900
restore receipt `tmp/current-step-ab-restore-1792573553886125200.json`.
Preflight must pass first. Save actual gate/encoder snapshots on any fault,
do not retry automatically and do not change thresholds again to chase PASS.
