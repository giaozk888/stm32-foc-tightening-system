# Current-step CL_BAD_OUTPUT: pre-closure evidence repair

Status: **diagnostic evidence defect repaired; underlying output mismatch NOT
yet attributed or claimed fixed**. No additional actuation/flash authorized or
performed during this change. Do not bypass CL_BAD_OUTPUT or change PI/limits.

## Why the two captures could not identify the writer

Both protected current-step attempts stopped during 0 A preparation, before any
0.10 A pulse. First protection flags16 (CL_BAD_OUTPUT), later aggregate48.
The original EmergencyOff closes SD/MOE/CCER before saving the existing fault
capture. Thus its off registers prove successful closure, not the failed
pre-closure predicate. Neither the later encoder fault nor the off BDTR proves
the original cause. No evidence supports changing gains/thresholds to fix this.

## Separate candidate, default disabled

Preset `CurrentStepAbGateEvidence` inherits the unchanged exclusive manual step
diagnostic, with `FOC_OUTPUT_GATE_EVIDENCE=1`. Ordinary A/B and original step
images have it disabled. It does not change the FOC math, gains, thresholds,
PWM pipeline, CUR_CONFIRM, discriminator, IRQ priorities or shutdown functions.

`ProtectedLoop_GatesMatch` uses the opt-in read-only observer. Its boolean
predicate is exhaustively checked against the original predicate. On the first
failed check while the guardian is armed, it records the *actual values read*
before the caller can run EmergencyOff:

- GPIO ODR (SD), the separate BDTR MOE and AOE reads, CR1 (CEN), CCER and SR;
- failed-input bitmask: CEN off / AOE on / SD unexpected / MOE unexpected /
  CCER unexpected, for the recorded session state;
- IRQ IPSR, return PC, DWT, timer timestamp, ADC sequence before/after;
- session before/used/after, armed flag and incoming PRIMASK.

The 80-byte record is binary, no ISR formatting/UART. Only the failed path
briefly masks IRQs while publishing the first record, restores original mask,
uses DMB and publishes valid LAST. Later faults do not overwrite it. This
adds bounded diagnostic work *before* the caller's software shutdown; its
latency and overall FOC timing require remeasurement. Independent hardware
protection and existing EmergencyOff are not modified.

Before/used/after state reads use an observer-only volatile view: generated
assembly initially showed GCC could merge non-volatile before/used reads.
ADC/state transition injection is tested so torn observations are explicitly
reported, not misrepresented as simultaneous peripheral reads. The record
identifies the checking caller/IRQ, **not automatically the writer** of a bad
register. If necessary that writer must be traced after the first capture.

`tools/foc_output_gate_evidence_report.py` decodes fields, verifies the captured
predicate and symbolizes the caller from the matching ELF. It is integrated
into the existing file-only `current_step_ab_report.py` after full image/ELF/
SRAM/Flash/stopped-receipt validation. No candidate capture exists yet.
Old ELFs report NOT_BUILT_IN_THIS_ELF, never decode arbitrary old SRAM as new.

## Build and offline verification

| Configuration | Flash B | RAM B | Result |
|---|---:|---:|---|
| New step gate-evidence A |213964|129704|PASS|
| Normal identified-PI A, isolated rebuild |217428|129160|PASS, BIN unchanged|
| Stable B, isolated rebuild |228300|128792|PASS, BIN unchanged|

All use RAM limit131008 B. Static free space is **not** a runtime stack-margin
measurement. Existing 12 unused diagnostics warnings and RWX linker warning
remain; syntax-warning comparison found no new warnings.

New BIN SHA256:
`9cb14e996ca42fddb6608d90d8eb7d3ea3aef9b58b31b78431c285a5222a2fb1`.
New ELF SHA256:
`3374f1577a6da5240af3b72f890f610531ae57e24bcdd36693d0c6f0f7d73418`.

40 relevant Python tests PASS: gate evidence5, original step6, board runner6,
identified PI5, one-cycle pipeline9, zero integration5, CUR_CONFIRM2,
independent overcurrent-confirm2. Host C binding is compiled/run at -Os/-O2;
coverage includes equivalent predicate, startup unarmed, good path, pre-off
values, first-record retention, valid-last, mask restoration and interrupted
ADC/session observation. No full unrelated repository-suite pass is claimed.

## Board disposition after OFF confirmation

Successful normal B restore receipt:
`tmp/current-step-ab-restore-1792572379371008800.json`.
Confirmed B896, pending none; B/boot/private/application bytes preserved;
VTOR0x08040000, DHCSR0x30003, SD0/BDTR0/CCER0. CPU halted at B entry,
B application not run, motor commands0. New diagnostic A not flashed.

Existing `current_step_ab_board.py` deliberately remains pinned to the old
BIN/ELF. It must not silently select this new untested build. A future manual
board request needs explicit new-image identity/ABI pins and the current
B896 restore as its validated OFF baseline, followed by one protected attempt.
No automatic retry, protection bypass or normal START is added here.
