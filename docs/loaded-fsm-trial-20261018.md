# 2026-10-18 original tightening state-machine trial

The preceding 20 rpm / 400 ms trial ran the original START entry and FSM. It
ended without a fault, but reached only 1.7 rpm in the captured telemetry.
The short interval does not establish steady speed or torque accuracy.

## Candidate

`LoadedFsmTrial` inherits `ProtectedPipelineClosedLoop` for A and B. It is
opt-in. The ordinary profile still has its original 400,000 us lease.

The loaded profile has one 12,000,000 us session per boot. Its 20 rpm admission,
60 rpm independent speed guard, current protection, sample/outer-loop guards,
CUR_CONFIRM, TWO_SAMPLE and one-cycle PWM pipeline are unchanged.

The original TighteningTask owns every transition:
RUNDOWN -> CONTACT_STOP -> SEATING_IQ -> TIGHTEN_010 -> TIGHTEN_012 ->
TIGHTEN_015 -> HOLD -> DONE, or an existing timeout/fault/STOP outcome.
It does not skip contact or fabricate a torque reading.

Admission requires the existing rundown timeout <= 8000 ms and the combined
five post-contact duration settings <= 1700 ms. The existing stop-settle timeout
is 2000 ms. The lease therefore covers this recipe plus 300 ms for task
transitions; recipes outside this budget are refused rather than rewritten.

The host runner temporarily changes only RUNDOWN_RPM to 20, keeps the existing
contact and current parameters, sends START once and records the observed
stages. It accepts full-cycle success only with all stages observed, CONTACT=1,
OUTCOME=OK and FLT=0. Its host deadline is 11.95 s. Completion or any failure
executes STOP and ANALOG SAFE, verifies outputs off and restores RUNDOWN_RPM.
It never persists the temporary recipe or automatically repeats START.

## Offline validation

- A: Flash 228,972 B / 229,376 B; RAM 127,944 B / 131,008 B.
- B: Flash 227,964 B / 229,376 B; RAM 127,928 B / 131,008 B.
- Both builds link successfully. Source warning comparison reports no new
  warnings; the existing RWX linker warning remains.
- Loaded lease/register mock tests: 25 scenarios at -Os and -O2, PASS.
- Host cycle runner: completion, fault cleanup, missing stage and excessive
  recipe cases, PASS (4 tests).
- Existing pipeline suite: 6 tests, PASS.
- Existing CUR_CONFIRM suite: 2 tests, PASS.
- Existing TWO_SAMPLE audit: 4 tests, PASS.

## Board preparation

Confirmed A631 was preserved. First B programming attempt timed out in the
OpenOCD RAM Flash algorithm. Full capture proved A/bootloader and all bytes
outside B unchanged, with no pending trial. The interrupted B was not selected.

The stage helper was corrected to reset/halt before Flash programming, clearing
application DMA/IRQ state. A subsequent controlled stage passed the complete
512 KiB readback comparison. Only the inactive B erase pages changed; confirmed
A631, bootloader, metadata and private regions are identical to their backup.

Staged B SHA256:
`1fd1afa9156bb72e71d42a16378d1e0a2cc76d167d9037dd5b3a869d63256826`.

## Actual board result

B completed normal boot-health confirmation as B634, with A631 preserved.
The first host readiness attempt stopped before START because its 5 s log wait
missed the 3 s MonitorTask / >=5 s timing-report phase. The helper now allows
12 s of read-only observation. One controlled reset of the already confirmed
B then passed startup and timing checks; no trial or START was repeated.

Exactly one START was sent for the workpiece cycle. During RUNDOWN, telemetry
initially showed approximately 0--4 rpm and increasing IqRef. At approximately
0.75 s of host elapsed time, the firmware latched CL_OVERSPEED (flags 1024).
The first-fault snapshot's FSM elapsed time is 720 ms. The contact stage was
never reached (CONTACT=0); this is a failed full-cycle acceptance.

Exact first-fault values from the loaded B ELF and halted RAM:

- Target speed: 20 rpm.
- Raw encoder speed: 91.5527 rpm; filtered speed: 60.6852 rpm.
- Position: 19.6216 degrees; encoder valid=1, encoder errors=0.
- IqRef: 0.03497 A; measured Iq: 0.06884 A; Id: -0.00341 A.
- Current validator state TRACKING, unresolved consecutive=0.
- CUR_CONFIRM: 314 enter / 314 clear / 0 fault.
- Outer FOC wall max: 28.9176 us; deadline miss=0.
- Real CCR commits: 703151; late=0; min margin=15.1882 us.

The longer window exposed overspeed rather than proving that the previous
0.4 s window alone explained the poor speed response. The snapshot does not
independently distinguish a mechanical acceleration from encoder feedback
error; no PI, feedback polarity, electrical angle or speed guard was changed
to force completion.

Cleanup acknowledged STOP, latched ANALOG SAFE (SD=0, MOE=0, FOC=0), restored
RUNDOWN_RPM from 20 to its original 70 and halted the MCU with outputs off.
Full Flash and RAM evidence remains in ignored tmp/ under prefix
`loaded-fsm-motion-1792300223073650000`.

No torque-accuracy qualification was performed.
