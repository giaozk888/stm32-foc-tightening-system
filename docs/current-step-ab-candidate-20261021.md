# Current-loop step A/B candidate — offline preparation only

No board write, boot-selection change, gate enable, current injection, or motor
start was performed in this change. Application B is untouched. Here **A_NEW /
B_OLD refer to the PI comparison labels inside ONE application-A image**, not
to alternating the physical A/B application slots.

## Files

- `firmware_common/current_step_ab.h`, `.c`: bounded one-shot schedule, accepted
  ADC-pair statistics, event trace, positive-to-negative quality gate.
- `firmware_common/current_step_ab_binding.inc`: local manual command,
  diagnostic-only reference owner and RTOS task; existing session/admission,
  PWM staging, output closure and fault paths are reused.
- `firmware_common/current_pi_identified_candidate.h`: runtime gain selection
  ONLY when `FOC_CURRENT_STEP_AB_DIAG` is compiled.
- `firmware_common/latest_original_fsm.inc`: exclusive diagnostic admission;
  normal FSM remains unchanged with this option OFF.
- `firmware_common/protected_closed_loop.inc`: diagnostic command routing only.
- `firmware_common/foc_startup_trace.h`, `foc_startup_trace_binding.inc`: this
  exclusive image uses 8 startup observation rows rather than 32 and reports
  the correct size. First-fault hooks remain; normal A/B still use 32 rows.
- `foc2_app_a/Core/Src/main.c`: reference hook immediately before the original
  current PI; capture hook after the original PWM pending stage. No PI math,
  angle, transforms, sample timing or pending/commit implementation changed.
- `foc2_app_a/CMakeLists.txt`, `CMakePresets.json`: default-OFF exclusive
  `CurrentStepAbDiagnostic` build; no application-B build option added.
- `tools/current_step_ab_report.py`: device-free decoder, per-step metrics and
  A/B comparison; no auto-selection or persistent PI writes.
- `tests/current_step_ab_host.c`, `current_step_ab_binding_host.c`,
  `test_current_step_ab.py`: actual C core, binding, runtime PI equivalence,
  frozen safety/pipeline, binary identity and decoder regression.

## PI gains

Units: Kp in V/A; Ki in V/(A·s). Existing integration order, 50us Ts,
integrator clamp and vector-voltage saturation/tracking remain unchanged.

| Label | Kp_d | Kp_q | Ki_d | Ki_q |
|---|---:|---:|---:|---:|
| A_NEW | 0.037755664 | 0.021073805 | 1470.26538 | 1470.26538 |
| B_OLD | 0.080000000 | 0.080000000 | 188.00000 | 188.00000 |

New gains use the previously user-selected candidate Rs=0.78Ω,
Ld=20.03µH, Lq=11.18µH and wc=2π×300rad/s. These provisional identification
values are not newly qualified by compiling this test.

## One manually initiated batch

Order: +.10 new/old, +.20 new/old, +.30 new/old, -.10 new/old,
-.20 new/old. IdRef=0. Each segment is:

`0A 20ms → selected fixed Iq 30ms → 0A 30ms`

Ten segments total at most 800ms. Actual excitation is only 300ms across the
batch. Each segment resets both current PI integrators and invalidates stale
pending through the existing handoff function during the zero preparation.
The one-cycle entry commit and current validator/hold policy are unchanged.
SPEED/POSITION/tightening and their S-curve/FF/friction outputs do not own the
reference. Existing IQ mode is selected with zero outer command; the bounded
reference is supplied only to the normal current PI at accepted ADC pairs.

References never exceed 0.30A; existing ±0.50A candidate limit, voltage limit,
300rpm independent overspeed, raw/current/encoder/deadline protections are not
increased or removed. The general direct-Iq setter's limit is not enlarged.
Its zero command selects IQ mode; admission also verifies that the existing
candidate current limit covers the complete diagnostic schedule.

Only one batch is accepted per boot. STOP cancels, output closure is immediate
through the existing stop path, and no fault clear/rearm/retry is performed.
The original session lease is not restarted between segments. An additional
diagnostic task timeout bounds the whole batch; it does not replace guards.

### Positive-to-negative gate (diagnostic quality, NOT protection thresholds)

All six positive segments must have:

- at least 80 accepted baseline samples in the final 5ms of preparation;
- at least 480 accepted pulse samples and 80 final-5ms samples;
- baseline within ±5% of target magnitude;
- 10% and 90% crossings, no >20% overshoot;
- final accepted samples in ±5% band for at least 5ms and mean error ≤5%;
- fewer than four alternating excursions past opposite ±5% band sides;
- no quantization clipping, and the post-zero phase must be observed.

Otherwise the batch finishes after the six positive segments with
`CS_POS_QUALITY_STOP`; negative segments are NOT_RUN, never silently counted
as passing. Any independent protection stops the entire batch immediately.

## Recording / metric definitions

Every **accepted** ADC pair contributes to statistics. Rejected/held pairs do
not get invented, interpolated or replaced in the diagnostic. ADC seq gaps are
counted. The compact trace stores six event frames per segment: last baseline,
first 10% crossing, first 90% crossing, peak, last high, last zero, plus an
optional failure frame. It is **not a full-rate continuous waveform**.

Each event contains relative ADC source timestamp, sequence, IqRef/Iq/Id,
Vq/Vd (limited), d/q PI integrators (after normal tracking), d/q PI outputs
(before vector limiting), voltage-saturation flag, electrical speed, step/PI
label, phase/status and protection flags. Current/voltage resolution is
0.1mA/0.1mV; speed resolution is 0.01 electrical rad/s. Clipping is flagged,
not hidden. Full first-fault and FOC/PWM timing snapshots remain separate.

- Rise: first90%-first10%, based on signed change from measured baseline.
  Same-sample crossings mean below sample resolution, not proven zero delay.
- Peak/overshoot: signed response amplitude relative to the commanded target.
- Settling: last entry to target±5% band, followed by ≥5ms accepted observations
  in band through the end of the 30ms pulse; otherwise NOT_SETTLED.
- Steady error: accepted mean Iq over the final 5ms minus target.
- Ringing: ≥4 alternating excursions beyond opposite ±5% band sides, a
  diagnostic noise-sensitive indicator rather than a fitted oscillation model.

Timing is measured from **ADC reference issue**, including the existing fixed
one-cycle pipeline. Metrics cannot resolve faster-than-sample behavior.
The offline A/B verdict requires complete rows, valid crossing/settling data,
no gaps/clipping, no fault/deadline miss/CCR late and positive actual margin.
It requires faster rise, no worse overshoot, shorter settling, no worse mean
steady error (0.1mA quantization allowance), no marked ringing. Otherwise it
reports mixed/not better or insufficient evidence, never auto-tunes.

FOC max/deadline/CCR timing statistics remain the existing boot/batch
aggregates, not per-segment timing histograms. No diagnostic counter reset
hides preflight or earlier failures.

## Build / offline verification

| Configuration | Flash bytes | RAM bytes | Result |
|---|---:|---:|---|
| A CurrentStepAbDiagnostic | 214300 | 130232 / 131008 | PASS |
| A CurrentPiIdentifiedCandidate | 217428 | 129160 | PASS; normal BIN unchanged |
| A CurrentPiLegacyCompare | 217420 | 129152 | PASS; normal BIN unchanged |
| B CurrentPiBUnchanged | 228300 | 128792 | PASS; stable BIN unchanged |

No new compiler/linker warning class or error. Each relevant build retains
the same 12 pre-existing unused-code/variable warnings plus the pre-existing
RWX LOAD-segment warning. The diagnostic keeps the existing heap/stack
reservations; static RAM headroom is 776 bytes, not a measured task-stack
high-water result. New instrumentation timing has NOT been board measured.

252 relevant tests pass: new step/binding/decoder 6, existing PI 5,
motor-identification 127, speed 81, PWM pipeline 9, closed-loop pipeline 6,
CUR_CONFIRM 2, encoder IRQ 7, fault trace 9. This is the named relevant suite,
not a claim that every unrelated repository test has been run.

## Manual board acceptance — NOT executed

1. With driver 12V OFF, mechanically lock the shaft using a rigid fixture fixed
   to the bench; fix the motor body, remove external workpiece/load, keep
   shielding. Do not restrain a shaft by hand. Verify U/V/W and signal wiring,
   12V supply/0.5A current limit and immediate power-cut access. This is a
   locked-rotor current-loop test, not the previous unlocked FSM test.
2. Separately authorize inactive-A transfer/readback and necessary boot under
   the existing A/B procedure. Preserve original confirmed B, boot/config and
   rollback evidence. No script in this change performs that procedure.
3. Power driver, check no alarm, complete normal zero calibration and the real
   timing/health preflight. Profile must report `NAME=CURRENT_STEP_AB`, not a
   normal FSM or power-hard-off image. Do not send START.
4. Once operator is present and all preconditions pass, send locally exactly
   once: `MOTOR TEST CURRENT STEP AB CONFIRM`. This arms the whole batch,
   including negative stages only after the six positive quality checks pass.
   Independent fault/uncertain shutdown ends the test with no retry.
5. After terminal status/output OFF, read `MOTOR TEST CURRENT STEP STATUS`,
   `... METRIC 0..9` and `... ROW 0..59` only while stopped. Save full UART,
   stopped SRAM, matching full Flash, exact ELF/BIN and same-session register
   evidence. Verify SD=0, MOE/AOE=0, CCER=0 before accepting closure.
6. Turn driver power OFF before restoring B selection through the existing
   recovery procedure. Do not confirm the diagnostic as production firmware.

Offline file-only analysis:

```powershell
# Plan only; no devices, no measurement result
python tools/current_step_ab_report.py

# Same capture receipt must contain halted=true, outputs_off=true,
# vtor=134250496 (0x08008000), and elf/image/ram/flash_sha256.
python tools/current_step_ab_report.py --elf foc2_app_a/build/CurrentStepAbDiagnostic/foc2.elf --ram stopped-ram.bin --flash stopped-flash.bin --receipt stopped-receipt.json --out step-ab-report.json
```

Do not treat a partial pulse, unobserved settling, quantization clipping,
missing timing proof or missing negative stages as a successful comparison.
