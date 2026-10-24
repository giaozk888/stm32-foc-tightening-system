# Candidate A: qualify DOB admission start and capture its first event

## Evidence behind this fix

Prior single run `tmp/mechanical-ident-run-1792722888869886400.json` had only56
admitted pairs and two isolated returns, then a diagnostic latch after~60 epochs,
well before600rpm steady state. Final stored candidate differed from its old
reference mainly in Iq (-0.30235A), not Id (-0.07079A). The existing jump selector
began at RUN/near-zero-speed, while the observer itself required20rpm minimum.
Its V2 trace waited for500ms at steady600rpm and captured only an already BLOCKED
state. We cannot prove the unrecorded unresolved pair was noise or physical current.

User requested repair. This changes only a new isolated A diagnostic preset,
`MechanicalDobAdmissionStartGuardCandidate`; it does not retune thresholds or
claim to solve all underlying dq current excursions. It is not yet board validated.

## One-way admission qualification

- New option `FOC_DOB_ADMISSION_START_GUARD`, default OFF, requires the isolated
  `FOC_DOB_SPIKE_ADMISSION` trace profile. Previous V1/V2 builds remain pinned.
- All original source validity, dt/sequence/age, saturation and fault checks run
  before qualification, exactly as before.
- Before arming: no new jump classification or budget consumption; existing
  current LPF and filtered-abs-Id50mA gate remain active for evidence. Published
  DOB stays INVALID, observer warmup remains zero. These are PREARM observations,
  NOT evidence that their raw values are clean and NOT valid model samples.
- Qualify using the EXISTING model minimum mechanical speed20rpm
  (`min_speed_rad_s=2.0943951...`), not a new safety threshold.
- Require same-sign speed above that minimum for50ms using actual dt. Falling
  below it, a direction reversal, or existing data-quality failure restarts
  qualification. A short speed excursion cannot arm.
- On the first qualified pair, reset observer and seed current filters/selector
  from that actual pair. No stale near-zero-speed current reference and no
  pre-arm warmup credit is carried into the model. Original~398ms observer
  warmup still starts from zero.
- Arming is one-way within the single-use run. An exit AFTER arming is still
  latched; neither good samples nor a later speed change silently clears it.
- Unchanged: jump0.25A, return0.15A, persistent-level confirmation0.05A, accepted
  gap2500us, second consecutive hold exits, fifth hold per32 epochs exits.
  Persistent new levels remain accepted/reseeded, not erased as isolated noise.
- No protection threshold, current/speed PI, FF, phase/angle, ADC selector,
  CUR_CONFIRM/CURRENT_INVALID, one-cycle PWM, IRQ or tightening logic changes.
  DOB stays SHADOW; nothing enters the Iq summing junction.

## First-event evidence

V3 no longer waits for steady600rpm before triggering. It captures the first
actual admission SUSPECT/BLOCKED, or armed Id-gate reset. It does not call a
PREARM transient an admitted/confirmed spike, and is not an automatic test/retry.

Reuses the same4608B buffer,48B per frame,16 pre +32 dense post +48 decimated
recovery=96 frames. Each frame retains raw signed Id/Iq, actual abs_id_lpf,
warmup, dt/status/reset/decision/exit flags plus ADC sequence, source/publication
timestamps, speed reference/measured speed and qualification time.
Dense data are~1kHz task observations, not all20kHz ADC samples or analog aperture.
Recovery>=4ms is decimated: intervening samples/events must not be invented.

New readonly `MOTOR TEST MECH DOB ADMIT ARM` reports confirmation interval,
existing minimum speed, armed state, qualification time, PREARM sample count and
arming timestamp. All protocol replies fit the existing192B buffer. No setter,
reset-latch command, observer feedback or persistence interface was added.

`dob_id_trace_report.py` decodes V1/V2/V3 separately and keeps historical board
captures valid. It handles PREARM zero warmup and reset-then-seed in one epoch;
V3 valid samples also check ADC publication and signed current/encoder relation.

## Files changed this turn

- `firmware_common/dob_current_admission.h`: one-way qualification and PREARM state.
- `firmware_common/mechanical_dob_monitor.c`: guarded start/reseed, no warmup credit.
- `firmware_common/dob_id_trace.h/.c`: V3 first-event trace/source evidence.
- `firmware_common/mechanical_dob_binding.inc`: readonly arming info/V3 identity.
- `foc2_app_a/Core/Src/main.c`: trace-only source timestamp arguments.
- `foc2_app_a/CMakeLists.txt`, `CMakePresets.json`: isolated opt-in preset.
- `tools/dob_id_trace_report.py`: backward-compatible V3 decoder/CSV.
- `tests/dob_admission_start_guard_host.c`, `test_dob_admission_start_guard.py`.

## Build/verification

A Flash215508B, RAM130616/131008B,392B remaining; no heap or stack shrinking.
BIN SHA256 `d8412b5629ff208f0549546cc526ef7e8e82a139c57c0fc2aaa67a5a4eaf7f98`.
ELF SHA256 `90439538958a1c4d1e707abe25a3ef5ae0789a1ed4a0a01c376a9ae3d03578e1`.
B review build passed, unchanged BIN
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
Existing unused/RWX warnings remain; main warning classes match V2.

Five new test methods PASS. Actual C at-Os/-O2 tests near-zero Iq transients,
same-sign qualification, brief speed/direction chatter, bad data, sign symmetry,
reset/reseed/no warmup credit, old50mA gate, isolated spike recovery and unchanged
post-arm latch. Synthetic trace triggers DURING acceleration (reference600rpm,
measured120rpm, steady timer0), retains trigger and next unresolved/exit pair,
source timestamps, sequence and canary-safe buffer. No board-effect claim.
Preprocessed control/protection functions match V2, and its old BIN hash remains
unchanged. V2 real capture still passes provenance decode. New readonly protocol
passes192B field-extreme tests. All134 related regressions PASS:
`tmp/dob-start-guard-regressions.log`.

## Board status and next validation

NO hardware/debugger access, flashing, activation, motor command or boot-selection
change during this turn. Last actual restore is original B under
`tmp/mechanical-ident-restore-1792723101035766500.json`.

Next manual test needs a NEW exact-V3-image-pinned board harness. Previous V2
harness must remain pinned and cannot safely run this candidate without adapting
identity,112B admission state, V3 frame and readonly ARM checks. Preserve all
existing OFF/stage, fresh ON/no-alarm, calibration/timing/stack, single600rpm,
shutdown/capture and B restore gates. Record PREARM/arm time and first event;
if post-arm admission still locks, retain it as failed quality rather than
raising bounds or retrying automatically. No claim of reliable usable DOB until
these actual paired waveforms and valid coverage are reviewed.
