# V6 candidate A: sustained Id and consecutive raw-jump quality

User explicitly accepted: previous-raw dq jump100mA,3 consecutive points before
exclusion; existing filtered absId60mA,20ms continuous high before unavailable.
Offline implementation/build only: no flashing, MCU reset or motor command.
Physical original B remains restored by1792727325095184200 (generation1067).

## Policy and exact semantics

Opt-in `MechanicalDobPersistentCandidate` inherits frozen V5 settings and adds
`FOC_DOB_PERSISTENT_QUALITY=1` (default OFF, no option in formal B).

1. `jump=max(abs(Id[n]-Id[n-1]),abs(Iq[n]-Iq[n-1]))`, in A, compared with
   `DOB_ADMIT_JUMP_A=.100f` strictly `>`. Reference is previous RAW finite,
   source-qualified pair even if that previous pair was excluded. It is not
   absolute current, deviation from IdRef or last-admitted current.
2. `DOB_ADMIT_JUMP_CONFIRM_POINTS=3`: runs1/2 are JUMP_PENDING and **admitted**
   to the actual LPFs/model, not secretly held; from run3 onward the pair is
   RUN_REJECT and invalid. Neither prior admitted sample is retroactively
   deleted. Either axis can contribute to the consecutive pair-level run;
   a point<=100mA resets it. A true single persistent current-level step does
   not remain rejected against an old baseline.
3. No count/rate session latch. The V5 short-gap freeze / invalid recovery and
   long-gap>10ms recoverable observer reseed remain. Recovery never implies
   a motor restart or clearing real protection. Raw-adjacent continuity breaks
   on existing source/time/sequence/saturation failures.
4. Id gate observes the same existing `LPF(abs(Id))`, tau20ms, limit60mA.
   `DOB_ID_BAD_CONFIRM_US=20000` is NOW a separate actual confirmation duration,
   not that LPF time constant. First observed above-limit filtered point starts
   at0us; subsequent consecutive admitted epochs accrue actual dt. At>=20000us
   the observer resets once, output is invalid while condition persists.
   Further high samples do not repeatedly reset its state. Runs do not accrue
   during missing/excluded/recovery epochs; pending time restarts after a gap.
   A confirmed bad condition is not cleared by lack of data.
5. Qualified filtered absId<=60mA clears confirmed condition; ordinary fresh
  5/g (~398ms at2Hz) warmup is still required before valid output. Disjoint high
   runs cannot be added together. This changes Id quality handling, not IdRef=0,
   d-axis PI or hard protection. First motion-arm epoch starts fresh state.

The first two suspected jumps deliberately enter the model; this relaxed
policy can reduce discarded points but does NOT remove noise, prove the points
are genuine or guarantee better disturbance estimates. An isolated raw spike
that drives the filtered amplitude high for20ms can still cause confirmed Id
unavailability. Source quality, speed/model validity, saturation and all real
protection may still independently invalidate/stop operation.

## Telemetry and memory

Readonly `MOTOR TEST MECH DOB ADMIT CFG`: MODE=PERSIST,POINTS=3,ID_US=20000,
REF=RAW,LATCH=0,FEEDBACK=0. New readonly `... ADMIT PERSIST` reports RUN,MAX_RUN,
PENDING,ID_US,ID_PEAK_US,ID_BAD,ID_ENTER,ID_RECOVER; reply fits192B even maximal
uint32 counters. No reference/actuator/config setter.

Admission RAM ABI160B (V5 was124); original monitor856B/header96B unchanged.
Trace V6 reuses4608B:16pre/32dense/48tail >=16ms. It replaces redundant per-frame
fixed qualification-time slot with actual Id bad timer; original qualification
remains in global admission state/UART. Former exit_reason16bits contain
saturating8-bit jump-run plus Id-confirmed bit8 in V6 only. Decoder explicitly
branches on ABI, rejects premature exclusion/Id reset or validity contradictions;
retains V1..V5 support. No full20kHz-waveform claim or dense tail replay.

Changed files: firmware_common/dob_current_admission.h,mechanical_dob_monitor.c,
dob_id_trace.h/.c,mechanical_dob_binding.inc; A CMakeLists/Presets;
tools/dob_id_trace_report.py; tests/dob_persistent_host.c,test_dob_persistent.py;
this record. No main control/IRQ or physical B edits.

## Offline verification and build

Native production C at -Os/-O2 with -Wall/-Wextra/-Werror covers isolated spike
and return admitted, third jump excluded, exact100mA both signs/axes, persistent
real level step, no count latch, short freeze and recoverable long gap,20ms
time boundary19999/20000us, interrupted timer, existing Id threshold equality,
single entry reset/not repeated per point, normal fresh rewarm, invalid source,
and real FAULT remains frozen. V6 raw buffer decode checks actual counter/time
fields, corrupt premature-confirm metadata and full192B protocol capacity.
Actual old V4 retained45-point dense replay:4 pending admitted,1 excluded,
no latch (V5 previously excluded5); not a full-session or hardware result.

Preprocessed FOC/current/speed/encoder/PWM/guard/readiness/task power-control
functions match V5. Main warning classes equal V5; existing unused-function and
RWX linker warnings remain. No new warning class.

A compile PASS:flash216196B,staticRAM130664/131008B (344B left), no stack/heap
shrinking. BIN SHA c6b35a3e8a420c7de811c72abdb09568f67b424602582dc9f94c940e8d7724a5;
ELF SHA5b0f5cc457cb4c705b2d0f3e6fd67346138e7a86ff4ec4441f9b44fedddb18af.
B review build PASS, unchanged SHA7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366.
Seven new focused test methods PASS. Related regressions:
`tmp/dob-persistent-regressions.log` (completion recorded separately below).
No physical A/B update, no observer feedback, no hardware validation in this turn.

Related regression completed:164/164 PASS (including7 new test methods), no
failed groups. Frozen V5 BIN hash and B review BIN hash remain unchanged.
