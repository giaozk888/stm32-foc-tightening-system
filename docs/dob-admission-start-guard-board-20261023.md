# V3 DOB admission start-guard: single +600rpm board validation

User confirmed physical12V OFF, MCU powered, shaft unlocked/unloaded motor
fixed with guard, unchanged U/V/W and IU/IV/SD wiring,12V supply limited0.5A,
operator present for immediate power cut. Inactive-A-only update, preserve B.

New exact-image-pinned harness `tools/dob_admission_start_guard_board.py`:
reviewed V3 BIN/ELF identity,112B admission and V3 trace ABIs, unchanged dq
thresholds, readonly unused50ms arming config, exact +600rpm single-run whitelist.
It first proves actual V2/B1055 restore
`tmp/mechanical-ident-restore-1792723101035766500.json`, retains original boot,
calibration, real timing/stack/readiness, single RUN, shutdown/capture and B restore.
Quality failure is reported, never retried automatically; no DOB feedback.
Four new harness tests and five core/trace tests PASS immediately before staging.

One run will require separate fresh ON/no-alarm confirmation after inactive-A
stage/two readbacks. No threshold or controller tuning during this board test.

Inactive-A stage `tmp/mechanical-ident-stage-1792724868862902400.json` PASS:
two complete readbacks, B/boot/private/metadata preserved, activation=false,
motor_commands=0, SD/BDTR/CCER=0, CPU halted. Separate fresh ON/no-alarm
confirmation requested; no motor motion yet.

## One supervised test completed; partial mechanism verified, quality NOT accepted

Fresh ON/no-alarm/operator confirmation received. Batch
`tmp/mechanical-ident-batch-1792724932301745200.json` PASS means safe acquisition
and stop closure only, NOT usable DOB. Run
`tmp/mechanical-ident-run-1792724932372082300.json` saved exact same-session
Flash/RAM and reviewed ELF/BIN provenance. RAM SHA256
`2ecf57c1dc44c018b639919ceaf75f0d594e15ddf24612bc88d63e1728c34024`.
No retry, threshold retuning, observer feedback or parameter write.

### Arming and whole-run outcome

- Original source/age/sequence/readiness checks and original guards retained.
- PREARM observations513; one-way arming timestamp8604228us, same-sign qualifier
  50998us. Unlike V2's~60-epoch near-zero latch, admission starts after qualified
  motion. The run subsequently produced265 valid DOB samples.
- Total8020 observations,7508 armed-admission inputs,1004 admitted pairs,
  21 suspects,18 isolated returns,2 transitions,1 unresolved,22 held epochs.
- Admission eventually latched again (one exit, reason2=second consecutive hold),
  around1.54s into RUN. Final pending timestamp9628177us; last accepted9627228us,
  accepted gap1999us. Exact next unresolved pair is not retained in this window.
- Whole-run valid265/8020=3.30424%; rejected6504. Pre-arm/low-speed/warmup and
  blocked observations are not magically made valid. V2 had0/8000, but a single
  uncontrolled run does not prove improved physical control or qualified filtering.
- Final reference/candidate Id+0.000810/-0.009292A, Iq+0.054275/+0.314944A;
  suspect distance was again mainly Iq (0.260669A), not Id. Unknown unresolved
  next point prevents asserting whether the final latch was false or justified.

### First-event trace now actually covers an anomaly during acceleration

V3 complete96 frames (16 pre,32 dense post,48 decimated tail), no encoding error.
Trigger8657219us, seq170782; steady qualification timer0. Speed reference93.214rpm,
measured74.966rpm: trace did NOT wait for600rpm steady state. This verifies the
first-event timing repair. The trace ends8904211us, ~725ms BEFORE final latch;
do not claim it captured that later exit or all21 events.

|Relative ms|Raw Id A|Raw Iq A|Decision|abs_id_lpf A|Warmup ms|Actual reset|
|---:|---:|---:|---|---:|---:|---|
|-2.013|-0.044193|+0.200796|NORMAL|0.031781|50.978|No|
|-1.000|-0.250983|+0.448712|NORMAL|0.042348|51.991|No|
|0|+0.009880|+0.147614|SUSPECT|0.042348|51.991|No|
|+1.001|+0.015382|+0.142787|TRANSITION|0.015382|0|Yes, then initialize|

The larger point at-1ms entered the LPF: distance from the prior pair was
0.247916A, just BELOW the0.25A jump threshold. Its return to lower current had
distance0.301097A, so the return was instead held as suspect. Next lower point was
only0.005502A from that candidate and classified as persistent new level, causing
observer reset/reseed. This demonstrates a directional entry/return asymmetry in
the adjacent-jump rule on this dq waveform. It does NOT prove the large point was
an ADC glitch or that physical current should have been removed.

At+19.992ms another suspect was followed by SPIKE_RETURN at+20.992ms. Both LPFs
held unchanged at the suspect, actual recovery point was invalid, no observer
reset and no warmup credit: this intended isolated-confirmation path worked on
retained data. Tail is decimated; some return/transition frames are not retained.

Dense checks:47 pairs, max Id LPF recurrence residual1.91e-9A, hold LPF change0,
reset/warmup contradictions0, max warmup increment error1.70e-9s. Actual source/
publication/encoder timestamps and ADC sequences retained, not analog aperture.

### Safety and timing

No first fault; no protection exit. FOC wall max33.6us, deadline miss0, CCR late0,
minimum actual CCR margin15.176471us. Preflight MotorCtrl free stack2548B.
SD/MOE/CCER shut down, CPU halted, all raw evidence saved. DOB never fed back toIq.

Exports: `tmp/dob-start-guard-board-1792724932372082300.json` and `.csv`.
Verdict: start qualification and first-event recording behaved as designed;
the overall dq admission candidate remains UNACCEPTED due to later latch and low
valid coverage. Do not simply increase thresholds or treat extra valid points
as proof. Further changes require studying waveform context/robust admission
and preserving any genuine sustained current changes. No second run performed.

Physical OFF confirmed after capture; original-B restoration initiated separately.

## Original B restored

`tmp/mechanical-ident-restore-1792725093959340300.json` PASS after user physical-OFF
confirmation. Original B/boot/config/app-private regions unchanged; B application
not run, motor_commands=0, SD/BDTR/CCER=0, VTOR0x08040000, CPU halted.
No further motor run.
