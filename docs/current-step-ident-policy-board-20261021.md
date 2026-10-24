# Identification-policy current-step board attempt — 2026-10-21

Result: calibration/health/timing/policy preflight PASS, but batch protected
ABORT in0A preamble. **No nonzero-reference pulse acquired, no new/old PI
performance comparison possible.** No automatic retry or further limit change.

Fresh physical OFF/locked fixture/fixed/shielded/wiring12V0.5A/operator
confirmation, inactive-A-only stage, then separate ON/no-alarm confirmation
were received. Exactly one normal trial + health-confirmation reset + one
manual diagnostic command. No normal START/tightening.

## Pinned artifacts and captures

- Image: `foc2_app_a/build/CurrentStepAbIdentPolicy/foc2.bin`214340 B;
  SHA256`20398c4906f1b1a6ba1fc6902cde68c0e1988fd0b64f6e091ff885c22e48f9d1`.
- ELF SHA256`5db4b36d06688ecc30fc0a011625be2d3a6245adf9f02f63f991df4bc4d0776e`.
- OFF stage `tmp/current-step-ab-stage-1792574508335334300.json`: two full
  readbacks PASS; original B900/boot/private/config/metadata unchanged;
  activationfalse, motor_commands0.
- Run `tmp/current-step-ab-run-1792574569225706000.json`; full same-session
  Flash/SRAM and hashes saved. New runner `tools/current_step_ident_policy_board.py`
  verifies exact firmware, complete restored baseline/root preservation and
  live policy before excitation. Original runners keep their own image pins.

Before/after live policy both POLICY2/TERMINAL_FIX1/WARN200/DEADLINE400,
SCHED200/PERIOD1000/AGE1500/CONTROL2500. Thus this is NOT accidentally running
the old200us cutoff. Successful-only timing stats SLOW_N0/OK_MAX151us exclude
the failed419us transaction; do not interpret them as a maximum of all attempts.

## First failed-gate tuple (captured BEFORE software EmergencyOff)

| Field | Value |
|---|---|
| ADC sequence before/after |156823/156823|
| session before/used/after |RUNNING/RUNNING/RUNNING (2/2/2)|
| observation context changed |false|
| caller |ProtectedLoop_PwmHealth, return PC0x200005cd|
| IPSR / source |34 / ADC1_2_IRQn|
| observer timer_us |7959330|
| GPIO ODR / SD |0 /OFF|
| BDTR first/second |0x02002055 /0x02002055; MOE0/AOE0|
| CR1 |0x31; CEN1|
| CCER |0x555, channels not yet cleared|
| mismatch bitmask |12: SD_UNEXPECTED + MOE_UNEXPECTED|
| armed / incoming PRIMASK |1 /1|

First protected snapshot flags16/CL_BAD_OUTPUT; later aggregate flags48 adds
CL_BAD_ENCODER. This finally proves WHICH predicate inputs failed, rather
than reading already-cleared CCER after closure. It is not direct proof of
the earlier register writer's PC; decoder correctly retains
writer_attribution=NOT_PROVEN_BY_REGISTER_READS.

## Encoder chronology and interpretation

| Driver evidence | Value |
|---|---:|
| transaction start |7958924us|
| absolute deadline |7959324us|
| phase/frame in driver failure snapshot |HOLD(4)/0|
| word RX timestamp |7959215us (291us after start)|
| guard_due |7959276us|
| failed-gate observer timestamp |7959330us (deadline+6us)|
| CL closure timestamp |7959335us|
| deferred driver terminal/snapshot time |7959343us|
| final elapsed / cutoff |419/400us|
| SPI SR / DMA ISR |2 /0|
| RX/TX NDTR |0 /0|
| attempts / successes / failures |6464/6463/1|
| timeouts / DMA errors / schedule misses / control stale |1/0/0/0|

Do NOT say outputs remained enabled for419us: they were already observed OFF
before the deferred terminal record. Register reads and observer timestamp
are not simultaneous hardware-latched events; the exact DeferOff entry time
was not recorded. No same-attempt success/duplicate-timeout pair was found.

Code `as5047p_dma_deferred.inc:DeferOff` clears MOE/AOE and SD, intentionally
leaving CCER/CEN and session state to the later normal fault hook. Timer-top
deadline handling can execute it before the lower-priority deferred service
publishes the encoder fault. The observed tuple, deadline ordering and sticky
AS_DMA_TIMEOUT match that mechanism, explaining why the ADC can report
BAD_OUTPUT first and encoder flags follow later. This is strong converging
evidence, not a new captured writer-PC trace.

400us did not cure delayed/incomplete protocol progression: investigate RX
event→deferred service→HOLD/GAP progression scheduling/latency and competing
IRQ load. Do not keep enlarging the cutoff, discard a transport failure as a
bad estimator sample, retune PI or bypass the output check to obtain a result.

## Control timing / disposition

- FOC wall max39.441176us; deadline miss0.
- actual CCR commits132777; late0; min margin14.852941us.
- CUR_CONFIRM50 enter/50 clear/0 fault.
- Last accepted step baseline at963us, IqRef0, Iq0.0338A, Id0.0109A;
  all ten pulse high-sample counts0.
- STOP and ANALOG SAFE acknowledged; debugger verified SD0/MOE-AOE0/CCER0,
  CPU halted and full Flash/RAM saved before fresh OFF confirmation.

After user confirmed12V OFF, normal B restoration PASS:
`tmp/current-step-ab-restore-1792574655503905800.json`.
Confirmed B904, pendingnone, B/boot/private/application payloads preserved,
VTOR0x08040000, SD/BDTR/CCER0, CPU halted before B application, motor_commands0.
No additional excitation or reset/automatic retry followed.
