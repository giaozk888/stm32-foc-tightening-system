# Step A/B board attempt — stopped before the first current step

Receipt: `tmp/current-step-ab-run-1792570483711951500.json`.
Exact candidate A BIN/ELF match the staged step image. One normal trial request,
normal firmware health confirmation across its reset, and one diagnostic batch
command only; no normal START and no excitation retry.

## Result

- Calibration and power-OFF-output preflight passed.
- Preflight wall max 31.776us, deadline miss 0, actual CCR late 0, min margin
  14.288us.
- The batch stopped in segment 0's 0A preparation phase, before its 20ms
  baseline completed. Last accepted event: 1065us after admission, seq156705,
  IqRef=0A. Every step's high-reference sample count is zero.
- Terminal diagnostic state5 / reason1 (protection abort), completed0/10.
- First-fault snapshot: domain2, reason3 (health protection), protection_flags16
  (`CL_BAD_OUTPUT` / output-state consistency). Later accumulated flags48 also
  contain `CL_BAD_ENCODER`; they must not overwrite or be mistaken for the
  first output-consistency fault. Encoder was valid with zero encoder errors
  in the first-fault snapshot. Exact cause of the gate-state mismatch is NOT
  established by the post-stop registers.
- Snapshot wall max38.217647us, deadline miss0; CCR late0, min actual margin
  14.288235us. CUR_CONFIRM46 enter /46 clear /0 fault. No evidence here of a
  50us deadline failure or a CUR_CONFIRM/current-discriminator fault.
- No rise-time, overshoot, settling or A/B PI comparison is available: the
  requested positive/negative steps were not executed. All remain NOT_RUN /
  INSUFFICIENT_EVIDENCE, not passing or zero-response measurements.

## Safe terminal state

Host STOP and ANALOG SAFE were acknowledged. The stopped same-session full
Flash/SRAM capture independently confirms CPU halted, SD=0, MOE/AOE=0, CCER=0,
VTOR0x08008000. A/boot/private/B payload unchanged by the run. Normal confirmed
A metadata generation891; B payload still227964 bytes / CRC627317606.

Driver12V shutdown confirmation is required before restoring original B
through the normal mailbox/bootloader process. Do not reset, re-enable, clear
protection, change gains/thresholds or retry the failed batch automatically.

## Drive-OFF recovery completed

After the user's fresh `12V OFF` confirmation, the original mailbox command
restored confirmed B and stopped at B's reset entry before application code.
Receipt: `tmp/current-step-ab-restore-1792570613506706900.json`, PASS.

- Metadata generation892, confirmed B, no pending/attempted trial.
- SD0 / BDTR0 / CCER0, VTOR0x08040000, CPU halted.
- Application A/B, bootloader and private configuration unchanged during
  recovery; B application not run, no motion/current command issued.
- No gains, limits, control or diagnostic firmware were changed after the
  failed test. The captured first fault establishes output-state consistency
  failure, but does not yet identify which register changed or its writer.

## Additional saved-evidence audit (no board access)

Exact-ELF SRAM re-decode: admission at7952409us; first output closure at
7953521us (1112us later), first fault publication timestamp7953522us.
`cl_startup.first_flags=16`, whereas later accumulated `cl_flags=48`.
`foc_pending_generated=22`, `foc_ccr_probe_blocked=1`, post-unsafe0,
hard-late0. A blocked CCR transaction is not evidence that lateness caused
the failure: its admission predicate also rejects an already-bad gate state.

TIM1 BKE/BK2E are disabled in MX_TIM1_Init; stopped BDTR0x02002055 also has
both enable bits clear. Therefore there is no evidence for a BKIN/BKIN2
hardware-break shutdown as the first cause. This does not qualify/disable the
separate driver-board protection, nor prove physical gate voltage from ODR.
The later encoder timeout reason8 is an ENCODER_TRANSACTION timeout; the first
fault had valid encoder and zero errors, so it cannot replace that first cause.

The exact failed output predicate is a compound check: CEN must be1, AOE0,
and when session RUNNING, SD-ODR1, MOE1, CCER0x555. No pre-closure register
tuple or register-writer provenance was retained. Stop/emergency-off then
overwrites the relevant registers. Existing records cannot distinguish which
operand first failed or prove a particular software writer/race. A targeted
first-failure register snapshot BEFORE closure is needed for that attribution;
do not bypass the check or alter gains/thresholds to obtain a passing test.

## Explicitly requested same-image retry

After fresh OFF/locked-fixture and then ON/no-alarm confirmations, one new
supervised attempt was made. No firmware changes or fault-threshold changes;
inactive A was independently read back twice, with `flash_programming=false`.
Stage receipt: `tmp/current-step-ab-stage-1792572188979916900.json`, using
the successful B892 restoration as the fully checked baseline. Host runner
now accepts explicitly selected successful restore receipts and preserves
their exact full-Flash identity check (6 transport tests PASS).

Retry receipt: `tmp/current-step-ab-run-1792572252465902700.json`.
Calibration/health/timing preflight passed, then one batch command was sent.
The same first fault recurred: protection_flags16 / CL_BAD_OUTPUT, IqRef0,
encoder valid/errors0. Last accepted preparation event was at161us after
admission, seq156884. No step acquired any nonzero-reference pulse samples.
All ten steps remain NOT_RUN; no PI rise/settling comparison is available.

Postflight wall max38.082353us, deadline miss0, CCR late0, actual min margin
16.652941us; CUR_CONFIRM45 enter/45 clear/0 fault. Later aggregate flags48
again do not replace the first flags16.

STOP and ANALOG SAFE acknowledged, full Flash/RAM saved, MCU halted,
SD0/MOE-AOE0/CCER0, confirmed A895. B/boot/private unchanged. No automatic
retry; original B restoration still requires a fresh driver-OFF confirmation.
Two reproductions justify instrumenting the pre-closure output predicate
instead of continuing blind same-image retries.

After fresh user-confirmed12V OFF, normal B restoration succeeded:
`tmp/current-step-ab-restore-1792572379371008800.json` (B896, pendingnone,
SD/BDTR/CCER0, CPU halted at B entry; B/boot/private/app bytes unchanged).
No motor command or B application run. Subsequent changes are file-only:
see `current-step-gate-evidence-20261021.md`; underlying mismatch not yet fixed.
