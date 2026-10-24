# Manual gate-evidence board attempt — 2026-10-21

Outcome: **target CL_BAD_OUTPUT did NOT reproduce**. Do not claim the output
fault is fixed. Instead, this attempt stopped on first flags32/CL_BAD_ENCODER
in the initial0 A interval. No nonzero-reference step pulse was measured.

## Exact image, staging and one attempt

New A `CurrentStepAbGateEvidence` BIN/ELF match the pins in
`current-step-gate-evidence-20261021.md`. `tools/current_step_gate_board.py`
explicitly selects this image, leaving the original runner's pins/default
unchanged. Both legacy/new-image restores require successful OFF restoration,
root B/boot/private matching, exact image/ELF/metadata and full Flash proof.
Default remains files-only. Transport tests cover both baseline identities,
missing physical confirmations, unknown ACK closure and no command retry.

Fresh OFF/locked/fixed/shielded/operator confirmation was received, then only
inactive A was written. Stage receipt:
`tmp/current-step-ab-stage-1792573401875534000.json`.
Two full readbacks PASS; B896 and boot/private/config/metadata unchanged;
activationfalse, motor_commands0.

After separate ON/no-alarm/12V0.5A/operator confirmation, exactly one normal
bootloader trial/health-confirm-reset was run. Calibration and5s timing
preflight passed. One `MOTOR TEST CURRENT STEP AB CONFIRM` sent; no normal
START, second batch or automatic retry. Original maximum batch800ms and
current amplitudes/protections unchanged; actual attempt ended in0A preamble.

Run receipt:
`tmp/current-step-ab-run-1792573490563630600.json`.
Matching full Flash and SRAM saved, original first-fault snapshot decoded.
Fault causes batch resultfalse; that is NOT a completed PI comparison.

## Measured evidence

- Pre-closure gate evidence: `valid=0` / NO_FAILED_PREDICATE_CAPTURED.
  Do not fabricate a gate tuple or attribute a register writer.
- First protection flags32 = CL_BAD_ENCODER, not earlier flags16.
- IqRef0A, Iq−0.01122A, Id+0.00738A at first protection capture.
- Startup off timestamp7933905us, start7933309us: about596us after admission.
- Encoder-valid1/errors0 in the synchronous protection snapshot is NOT proof
  the transaction succeeded; the driver deferred-fault evidence below is from
  its own first failure. Saved final encoder-valid0, timeout_reason8.
- FOC wall max39.788235us, deadline miss0, actual CCR count132265,
  actual late0, min margin15.947059us.
- CUR_CONFIRM39 enter/39 clear/0 fault.
- All ten pulse high-sample counts0; no A/B rise/settling verdict.

## Encoder driver's independent first-failure evidence

Decoded with file-only `tools/encoder_saved_fault_report.py`, requiring exact
saved SRAM hash and this same ELF. Source RAM:
`tmp/current-step-ab-run-1792573490563630600-ram.bin`.

| Field | Value |
|---|---:|
| status |2 / AS_DMA_TIMEOUT|
| phase at snapshot |2 / AS_DMA_WORD|
| frame |1|
| transaction started_us |7933699|
| deadline_us |7933899|
| fault now_us |7933900|
| elapsed / budget |201 /200us|
| deadline excess |1us|
| last word RX timestamp |7933753|
| RX/TX NDTR |0 /0|
| SPI SR |2|
| DMA ISR |0|
| snapshot IPSR |70|
| transaction attempts / successes / failures |6439 /6438 /1|
| timeouts / DMA errors / schedule misses / control stale |1 /0 /0 /0|

Previous successful publication seq6438 completed at7932796us (106us), last
failed seq6439 at7933900us (201us). This is NOT the historical same-attempt
success-then-duplicate-timeout pattern. RX/TX NDTR0 does NOT independently
prove the software completion/publication was handled before deadline. Exact
interrupt PC/entry or preemption breakdown at this transaction was not saved;
cannot yet blame sensor/wiring versus delayed completion/deferred processing.
Next investigation should track those completion/deferred-service times,
not raise current, tune PI or weaken the transaction/output guard.

## Safe disposition

STOP and ANALOG SAFE acknowledged; debugger verified SD0, MOE/AOE0, CCER0 and
CPU halted before fresh user OFF confirmation. Then normal B restoration:
`tmp/current-step-ab-restore-1792573553886125200.json` PASS.
Confirmed B900, pendingnone, SD/BDTR/CCER0, VTOR0x08040000, CPU halted at B
entry, B application not run, motor_commands0. A/B payloads, bootloader and
private/config unchanged by the restore. No further test performed.
