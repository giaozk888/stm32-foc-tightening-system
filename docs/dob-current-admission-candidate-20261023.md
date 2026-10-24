# Candidate A: bounded dq-pair admission for DOB observations only

## Scope and status

User approved reusing the historical suspect/confirm/isolated-spike rejection
idea in the DOB observation branch. This is NOT a rewrite of the 20 kHz raw
IU/IV TWO_SAMPLE selector and does not repair the motor's physical current.

Preset: `MechanicalDobSpikeAdmissionCandidate`, inheriting the isolated trace A.
Option `FOC_DOB_SPIKE_ADMISSION` defaults OFF, requires the diagnostic trace
profile, and is absent from B. No upload, debugger operation, activation or motor
command was performed during this implementation. Last board state remains the
original B selection restored under
`tmp/mechanical-ident-restore-1792721158187369200.json` after physical power OFF.

DOB is still SHADOW only. No observer estimate enters the Iq command.

## Input domain and initial hypotheses

The task sees coherent accepted dq pairs at approximately 1 kHz, after the
existing 20 kHz ADC selector and Clarke/Park. It does NOT receive all ADC pairs.
Distance is `max(abs(delta Id), abs(delta Iq))`, in A; pairs are never channel-mixed.

|Macro|Initial value|Meaning|
|---|---:|---|
|DOB_ADMIT_JUMP_A|0.25 A|Strictly larger adjacent accepted-pair jump becomes suspect|
|DOB_ADMIT_RETURN_A|0.15 A|Current pair returns near the pre-suspect pair|
|DOB_ADMIT_CONFIRM_A|0.05 A|Current pair coherently near the suspect new level|
|DOB_ADMIT_MAX_HOLD_US|2500 us|Maximum gap from last accepted observation|
|DOB_ADMIT_MAX_CONSEC_HOLDS|2|Second consecutive unresolved/held pair exits observation|
|DOB_ADMIT_WINDOW_SAMPLES|32|Fixed, non-overlapping observation budget window|
|DOB_ADMIT_MAX_WINDOW_HOLDS|4|Fifth hold within a window exits observation|

These are diagnostic admission settings, NOT protection thresholds or a statement
that large Id is necessarily noise. Prior dense Id trace had adjacent-jump P95
0.144 A versus trigger jump0.585 A, providing an initial separation hypothesis.
Return tolerance0.15 A avoids blindly transplanting the 40-count /50us raw rule
to a 1ms rotating-dq measurement. It still needs board evidence. No evidence exists
yet for corresponding actual Iq at the old trigger: old trace ABI did not record it.

## Decisions and time handling

1. Existing current validity, finite checks, source age, dt/sequence checks and
   saturation rejection run FIRST, unchanged.
2. A normal current pair feeds the existing current LPFs and shadow observer.
3. A suspect pair is retained as raw evidence but does NOT enter either Id or Iq
   LPF. Observer dynamics/warmup are paused. Published current observation is
   invalid, matched-current/estimate output zero, never a fake repeated sample.
4. If the next pair returns near the old level, the suspect is classified as an
   isolated spike. Only the actual return pair updates both LPFs and observer
   using the true <=2.5ms accepted gap. This is an explicitly bounded endpoint
   approximation, not recovered missing current/omega data. Return point remains
   INVALID and earns NO warmup credit; next normal point can become valid.
   A previously accumulated warmup is preserved, not reset for an isolated spike.
5. A coherent persistent new level is NOT discarded as noise. Reset the old DOB
   state and seed LPFs with the actual new pair, then initialize the observer.
   The original filtered-abs-Id >0.05 A gate still runs and can immediately reset.
6. Ambiguous consecutive pairs, excessive holds, invalid gap/input latch a
   diagnostic exit. Subsequent good samples cannot silently re-arm it. Existing
   quality failure/reseed does NOT clear this latch or its counters.
   Motor protection/control are not altered by this local diagnostic latch.
7. STOP/fault retains existing lifecycle reset/freeze behavior. No automatic retry.

This does not remove sustained Id excursions or continuous subthreshold jumps.
For example alternating +/-0.06A does not trigger this0.25A selector, and still
fails the original 50mA filtered-abs-Id gate. The20ms LPF and~398ms warmup remain.

## Evidence and ABI

- `MechanicalDobMonitor` stays856B; current/ring frame stays44B.
- New admission state92B: last accepted/candidate pairs, decision/exit reason,
  accepted gap, isolated/transition/unresolved/hold/budget counters.
- Reuse the same4608B mechanical bin buffer (trace-only marker remains unchanged).
- V2 trace:24B/frame,32 pre +32 dense post +128 decimated recovery =192 points.
  Signed raw Id/Iq, actual abs_id_lpf, warmup, dt, actual reset/valid/initialized/
  seed/trigger flags, admission decision and exit reason are retained.
- Trigger after the same500ms600rpm qualification, on first suspect/blocked/ID
  reset; no automatic retrigger. Tail>=4ms, not continuous ADC waveform.
- `dob_id_trace_report.py` reads V1 and V2 separately. It does not interpret
  decimated raw values as consecutive LPF inputs. Actual raw pairs remain visible.
- Readonly UART: `MOTOR TEST MECH DOB ADMIT CFG`, `... ADMIT`, `... ADMIT STATS`,
  and `MOTOR TEST MECH IDTRACE`. No ON, setter, protection-clear or persistence API.
  Replies fit the original192-byte buffer including counter extremes.

## Unchanged control and protection

Preprocessed control/protection functions match the previous trace candidate:
FOC_CurrentLoopStep, encoder speed/electrical angle, ADC/guard IRQ path,
ProtectedLoop readiness/task service, admission, powerstage, speed/Iq setters,
and tightening task. Only the task-only observer call receives local admission;
conditional trace arguments/log format change. No current/speed PI, S-curve,
friction/acceleration/BEMF FF, phase mapping, angle zero, current sampling,
CUR_CONFIRM, CURRENT_INVALID, hard overcurrent, PWM pipeline or IRQ priority change.

## Build and offline verification

- A: Flash214936B; RAM130592/131008B (416B remaining); no heap/stack reduction.
- A BIN SHA256 `e502d52c4c4d402f8a17a530aec9aa7925e11c1cf516d600da3cf7ff4dc862c0`.
- A ELF SHA256 `4dfbc0c01f575f8856740ff8714c2560af49337b0c9d50078bca2d0094341eeb`.
- B review build passed with BIN unchanged:
  `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
- No new A main warning class; existing unused and linker RWX warnings remain.
- Native `-Os` and `-O2` tests cover normal, positive/negative isolated spikes,
  Iq-only spike, paired filtering, persistent signed levels, persistent Iq step,
  original50mA gate, actual reset hook, no warmup credit on recovery, rate/consecutive
  exits, no re-arm, source gap/wrap/NaN, existing saturation/current failure,
  fault/STOP, trace buffer canary/ABI/decoder, readonly protocol and frozen functions.
- A fixture uses the recorded trigger/next Id numbers with SYNTHETIC constant
  Iq and synthetic prehistory. It is NOT a replay/proof of actual paired rejection.
- Final related regressions:124 tests PASS, `tmp/dob-spike-regressions-final.log`.
  New test result: `tmp/dob-spike-tests-final.log`.

## Next manual validation (not performed)

Prepare an exact-image-pinned board harness for V2 before writing A: the previous
`dob_id_trace_board.py` intentionally pins V1 and must NOT be used to flash this
new image by weakening identity checks. Preserve original B and all existing
calibration/timing/stack/stop checks. After separate physical OFF/stage and fresh
ON confirmations, run one same-config +600rpm unloaded observation. Compare raw
Id/Iq, admission decision, actual LPF, reset and warmup, valid coverage and timing
against V1; retain any early diagnostic exit as a result, no auto retry. More valid
points do not by themselves prove noise removal or a better physical current loop.
Then request physical OFF and restore original B. DOB feedback remains disabled.
