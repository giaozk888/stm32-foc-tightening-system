# DOB dq admission single +600rpm board test

## Preparation

Fresh user confirmation:12V OFF, MCU powered, shaft unlocked/unloaded motor
fixed/guarded, unchanged power/signal wiring,12V supply limited0.5A, operator
present for immediate power cut. User authorized inactive-A-only supervised test.

New `tools/dob_current_admission_board.py` pins the exact reviewed V2 BIN/ELF,
the previous real B1051 restore,92B admission/96B trace/856B monitor ABIs,
threshold config and unused trace/admission checks. It retains original boot,
calibration, real timing/stack, readiness, one RUN, shutdown/capture and B restore.
No parameter or protection relaxation; no automatic retry or DOB feedback.
New five harness tests and five core/decoder tests PASS before stage.

Stage `tmp/mechanical-ident-stage-1792722805217046400.json` PASS:
two full independent readbacks; original B/boot/private/metadata unchanged;
activation=false, motor_commands=0, SD/BDTR/CCER=0, CPU halted.
Separate fresh ON/no-alarm confirmation requested. No motor run yet.

## Single run completed, observation admission NOT accepted

Fresh ON/no-alarm/operator confirmation received. One +600rpm mechanical diagnostic
run completed with original5s drive/deceleration, ~8s total, no retry, no feedback.

- Batch receipt `tmp/mechanical-ident-batch-1792722888702819500.json` PASS for
  safe acquisition/closure, NOT a successful DOB qualification or parameter fit.
- Run `tmp/mechanical-ident-run-1792722888869886400.json`.
- RAM SHA256 `8e6a9c18279fb11675134f74365b48b7fde4b58dd67d17b20e0d45f5a1c583e7`.
- Exact image, V2 ABI/config/unused admission, calibration, readiness and stack
  checks passed. Preflight MotorCtrl free stack2504B.
- FOC wall max33.241176us; deadline miss=0, CCR late=0; actual commit min
  margin15.164706us. No first fault, encoder timeout/DMA/schedule/control-stale fault.
- SD/MOE/CCER off, CPU halted, full Flash/RAM saved.

### Admission results

|Whole-run measure|Result|
|---|---:|
|Observations|8000|
|Admitted pairs|56|
|Suspect candidates|3|
|Isolated returns|2|
|Persistent transitions|0|
|Unresolved|1|
|Held epochs|4|
|Latched diagnostic exits|1|
|Exit reason|2 = consecutive holds|
|DOB valid points|0|
|DOB quality rejected observations|7944|

Exit occurs after approximately the first60 observations, before steady state.
The remaining motor run is not a protection bypass: DOB is observation-only and
the latch cannot enable/control the motor. Original independent protection remains
active and no protection fired. The task correctly keeps the DOB output invalid.

Retained admission reference/candidate:

|dq pair|Id A|Iq A|
|---|---:|---:|
|Last accepted reference|-0.00731535|+0.00257222|
|Suspect candidate|-0.07810447|-0.29978043|
|Difference|-0.07078912|-0.30235265|

Thus the saved final candidate was made suspect by the **Iq** change exceeding
0.25A, not by Id change nor the original filtered-Id50mA gate. The next unresolved
pair itself was not retained in the late trace, so its exact coordinates cannot
be reconstructed and this is not proof of an actual electrical current spike.
The final reference/candidate values are raw recorded state, not inferred waveform.

### Trace coverage limitation

V2 trace is complete as configured:32 pre +32 post +128 tail=192 frames, encoding
errors0. However, it only triggers after500ms of steady600rpm and by then admission
had already latched. The captured window is entirely BLOCKED (from~11.757s to
12.389s device time), not the first exit at~8.15s. All192 retained points have
invalid DOB output, LPF abs Id7.570mA and warmup0. A low frozen LPF is **not**
evidence that filtering improved actual current, and zero recurrence residual
on frozen data is not a dynamic filter validation result.

State counter says two isolated candidates were excluded before the latch; the
late trace cannot verify their exact raw pairs or the offending unresolved pair.
The gating timing and startup-state coverage are therefore inadequate to conclude
this configuration is usable or better than the previous V1 (548/7880 valid).
Do not interpret this uncontrolled one-run comparison as a physical control effect.

Files-only exports: `tmp/dob-admission-board-1792722888869886400.json` and `.csv`.
No parameters, thresholds, phase/angle or control code were changed during testing.
No automatic second run or re-arm. Physical12V OFF requested before original-B
restore; await that separate user confirmation.

### Next evidence recommendation (not implemented/tested here)

Capture the FIRST suspect/exit from the beginning of RUN, independent of steady
qualification; include both dq raw pairs, source seq/time, speed/reference and
decision. Determine how startup/low-speed observations should seed/arm a
diagnostic admission filter instead of latching a whole session before the DOB
even reaches its valid speed. Do not simply raise limits or delete real Iq load
changes; assess paired decisions against actual waveforms. No new board test
authorized by this recommendation.

## Original B restored after physical OFF confirmation

User answered the explicit OFF request with confirmation. Restore receipt
`tmp/mechanical-ident-restore-1792723101035766500.json` PASS. Original B, boot,
configuration and app-private regions preserved. B application not run,
motor_commands=0, SD/MOE/CCER off, CPU halted. No further test performed.
