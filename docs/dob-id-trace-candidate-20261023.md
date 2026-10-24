# Same-epoch Id / abs_id_lpf / reset / warmup diagnostic A

User requested one +600 rpm unloaded retest. Fresh physical OFF/setup confirmation
received; activation requires a separate fresh ON/no-alarm confirmation.

## Unchanged behavior

No Id gate, LPF, observer warmup/reset policy, model, PI, FF, PWM pipeline,
sampling, IRQ priority, current validator, watchdog or protection changes.
The observer remains SHADOW only: it never enters the Iq summing junction.
The conditional reset hook runs AFTER the original observer reset and only
counts events inside a task observation epoch. Lifecycle resets are excluded.

## Storage and acquisition

- `MechanicalDobIdTraceCandidate` inherits the isolated DOB shadow profile.
- Reuses all 4608 bytes of `mechanical_capture.points`. Mechanical bin recording
  is disabled only in this diagnostic. Metadata remains ABI-compatible and marked
  `flags=0x80000000`, `count=0`; this run cannot be used for mechanical parameter fitting.
- Trace header 96 B plus backing pointer; no heap/thread-stack reduction.
- 16 B frame: signed Id_meas, actual abs_id_lpf, actual observer elapsed_s,
  interval_us, status/actual reset/valid/initialized/filter-seeded/trigger flags.
- Records ~1 kHz task observations, not every 20 kHz ADC sample or analog aperture.
- After reference reaches 600 rpm, acceleration <=1 rpm/s and measured speed within
  ±12 rpm continuously for 500 ms, trigger on the first actual ID reset call.
- Rolling 64-frame prehistory; trigger plus 63 dense post frames; 160 recovery frames
  spaced >=4000 us. Tail can omit intervening reset events; global reset call count
  covers the run. `recorded_reset_calls` counts calls at frame writes, including
  overwritten prehistory, NOT necessarily reset events still retained in the ring.
- Freeze on completion/STOP/fault. No retrigger/retry. No qualifying event means
  explicit untriggered partial prehistory, not invented recovery evidence.
- Timestamp overflow, cadence and terminal metadata checked offline.
- `MOTOR TEST MECH IDTRACE` is readonly and fits the existing 192-byte reply buffer.

## Interpretation

20 ms is the time constant of LPF(abs(Id)); there is no 20 ms reset dwell timer.
LPF above 50 mA invokes reset on that same observer call; ID reset does not clear
the current LPF. Observer warmup restarts at zero and needs 5/g (~398 ms).
Other quality failures may clear have_sample and cause LPF reseeding.
Dense data allow direct LPF recurrence/warmup checks. Decimated recovery raw Id
must NOT be used as consecutive filter inputs; only actual recorded LPF is valid.

## Verification before staging

- A: 213688 B Flash, 130504/131008 B static RAM, 504 B remaining.
- BIN SHA256 `6a56188d07032d3930be07a8172bb6fc0cb24dd5cb8424acbc5af266e4c4c0b1`.
- ELF SHA256 `e73e53acb9037dcbe1168b11919b32d751870f56c3e36f3facab3f8037581722`.
- B local review build passed; BIN hash unchanged:
  `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
  This does not replace the physical original B.
- 10 new tests PASS: actual native reset hook, LPF/warmup, wrap/jitter, quality
  gap/reseed, partial bad time, no event, decoder corruption, readonly protocol,
  exact image identity, physical gates and frozen control/protection function checks.
- 109 related regressions PASS (`tmp/dob-id-trace-regressions.log`). No new A main
  warning class relative to DOB shadow; existing unused/RWX warnings remain.

## Board procedure

`tools/dob_id_trace_board.py` retains original full-image identity, inactive-A-only
staging, two readbacks, boot/config/private/B preservation, calibration, real timing
and stack preflight, exact +600 rpm single-run whitelist, safe shutdown and complete
same-session Flash/RAM/ELF provenance checks. Starting restoration root is B1047
`tmp/mechanical-ident-restore-1792718646428222500.json`.
After fresh ON confirmation execute exactly once. Any independent fault stops the
test without retry. After output-off capture/halt ask physical OFF, then restore
original B selection without running its application. Record actual result separately.

## Inactive A staged, awaiting fresh ON

`tmp/mechanical-ident-stage-1792720991699612700.json` PASS:
two full readbacks passed; original B/boot/private/metadata preserved;
activation=false, motor_commands=0, final_outputs_off=true, final_cpu_halted=true.
No motion test has occurred. Fresh ON/no-alarm confirmation requested separately.
