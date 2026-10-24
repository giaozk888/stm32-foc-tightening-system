# Candidate A dq decoupling audit — 2026-10-21

## Scope / result

Code review, offline replay, host regressions and four ARM diagnostic builds
only. No serial/debugger connection, flash, reset, boot-selection change or
motor start. Stable B image remains unchanged. No gain, protection threshold,
current admission, CUR_CONFIRM, trajectory, PWM pipeline or IRQ change.

No software sign/unit/voltage-limit bypass has been found. The worsening
startup/acceleration metrics are **not yet causally explained**. One OFF/ON
pair, different initial rotor positions/calibration and alternating sparse
queries cannot establish that compensation caused the difference.

## Actual angle and voltage convention

`foc2_app_a/Core/Src/main.c`, `FOC_CurrentLoopStep`:

```
alpha = Iu
beta  = (Iu + 2 Iv) / sqrt(3)
Id = alpha cos(theta) + beta sin(theta)
Iq = -alpha sin(theta) + beta cos(theta)
alpha_voltage = Vd cos(theta) - Vq sin(theta)
beta_voltage  = Vd sin(theta) + Vq cos(theta)
```

Differentiating this actual rotation gives `d(Park)/dt = -we J Park`.
Transforming the stator voltage equation therefore gives the inductive
coupling terms `-we Lq Iq` and `+we Ld Id`. Existing nominal compensation:

```
Vd_dec = -we_rad_s * 0.00001118 H * Iq
Vq_dec = +we_rad_s * 0.00002003 H * Id
```

These signs match the code's rotation convention. They do not prove physical
phase wiring or electrical zero. No back-EMF/flux term was added. Independent
finite-difference Park tests and real encoder helper tests cover both signs
of mechanical motion, wrap and the existing direction = -1.

Reference for the voltage-equation derivation, not substituted for source
inspection: [Microchip MCAF FOC equations](https://microchiptech.github.io/mcaf-doc/6.0.2/algorithms/foc/introduction.html).

## Electrical speed / inductances

`FOC_EncoderSpeedUpdate` consumes accepted encoder DMA snapshots in the
existing task processing path. Raw delta/dt produces signed mechanical rpm;
the existing 20 ms low-pass produces `encoder_speed_rpm`:

```
mech_rad_s = encoder_speed_rpm * 2*pi / 60
encoder_omega_e_rad_s = 10 * mech_rad_s
```

Pole pairs occur once. Existing `ENCODER_DIRECTION=-1` is applied consistently
to angle and speed, not repeated in decoupling. The ADC uses that same signed
electrical rad/s variable, not rpm or unsigned speed.

- Normal 300 rpm overspeed boundary corresponds to 314.159 rad/s electrical.
- This is a protection boundary, **not an explicit clamp of `we`**. The speed
  publisher runs before its overspeed stop check; do not claim a strict
  mathematical maximum of 314.159 for every transient frame.
- Saved sparse OFF/ON STATUS observations: max |we| = 254.376 / 253.654 rad/s.
  These are observed maxima, not full-rate peaks.
- The LPF inherently lags acceleration. Its presence alone does not prove the
  additional 175 ms startup delay. At we=0 both compensation terms are exactly
  zero. At 240 rpm and |Iq|=0.5 A, |Vd_dec| is only about 1.405 mV.
- Task writes of mechanical speed and electrical speed are separate. The ADC
  can observe different publication generations. New audit measures the
  mismatch but deliberately does not alter that owner or angle prediction.

`FOC_DQ_LD_H=0.00002003f`, `FOC_DQ_LQ_H=0.00001118f`: H, namely
20.03 / 11.18 uH, not values mistakenly interpreted as H or mH. These remain
user-selected provisional identification estimates, not qualified parameters.

## Integration / saturation

Unchanged path:

```
normal accepted ADC pair -> current PI -> existing integral clamp (+/-0.75 V)
 -> Vd_PI + Vd_dec, Vq_PI + Vq_dec
 -> existing common 1.60 V vector voltage limit
 -> inverse Park -> SVPWM -> one-cycle pending PWM
 -> existing next-ADC-entry commit
```

The existing saturated PI tracking subtracts the feedforward contribution
before its unchanged integral clamp. No compensation bypasses the common
vector limit. Diagnostic recording is after this limit, before inverse Park.
`Vd_cmd/Vq_cmd` are final dq commands, not proof of physically applied voltage
at the ADC sample instant; the one-cycle pipeline remains unchanged.

## What old data can / cannot establish

Saved runs:

- OFF `tmp/dq-fsm-run-1792579105569898700.json`
- ON `tmp/dq-fsm-run-1792579317512317700.json`

Each contains 16 STATUS and 15 VOLTAGE replies alternating approximately
250 ms apart. Different replies have different ADC sequences. **There is no
VOLTAGE reply in the first 500 ms.** Do not merge them into a fabricated
same-frame sample or claim startup/standstill maxima.

- ON observed Vd_dec: -609..-115 uV; Vq_dec: -198..+405 uV.
- ON `Vcmd - Vpi - Vdec` at unsaturated voltage observations differs by at
  most 1 uV from independent wire-unit rounding.
- Observed mean Vq_cmd OFF = 0.355521333 V; ON = 0.354916800 V.
  Difference = -0.000604533 V. Different operating points/PI response are
  included; this is **not** the isolated compensation effect.
- All 15 observed voltage saturation flags are zero. Sparse observations
  cannot rule out earlier/transient saturation.
- Earlier `SAT_MS=0` measures **speed-loop Iq saturation**, not dq voltage
  saturation. It must not be reused as voltage-saturation evidence.

Offline replay (no device access):

```
python tools/dq_decoupling_audit_report.py --off tmp/dq-fsm-run-1792579105569898700.json --on tmp/dq-fsm-run-1792579317512317700.json
```

Unavailable startup/stationary maxima and earlier voltage saturation return
null, not a guessed zero.

## New diagnostic evidence

`FOC_DQ_AUDIT_ENABLE` defaults OFF. In opt-in candidate A:

- Every accepted normal PI frame accumulates near-stationary maxima
  (|filtered mechanical rpm|<=1), first 500 ms maxima, cruise compensation
  sums/counts, actual common-vector saturation count/first elapsed us,
  |we| max, mechanical/electrical conversion mismatch and sign/math checks.
- Start time is the first accepted normal PI frame in `CL_RUNNING`, using
  ADC source microseconds. Cruise classification requires the existing
  S-curve to have reached its current command with zero reference acceleration.
- Held/rejected frames are excluded; their control behavior is untouched.
- After the run, the final running frame and statistics are retained. Audit
  is reset by normal image reset; do not reuse one boot for multiple STARTs.
- ISR: fixed binary record/arithmetic only. No printf/UART, allocation,
  RTOS calls, timer changes or output enable. Audit body is ordinary Flash
  `.text`; caller/veneer and data still add some RAM/code overhead.
- MonitorTask copies a bounded 148-byte coherent snapshot, restores IRQ state
  before logging, emits frames at 100 ms and statistics at 1 s.
- Four compressed same-sequence rows R/S/I/V contain:
  seq, ADC timestamp us, run elapsed us, ON/sign mode/state/saturation flags,
  mech_rpm, we_rad_s, Id, Iq, Vd_PI, Vq_PI, Vd_dec, Vq_dec, Vd_cmd, Vq_cmd,
  speed_ref, speed_meas. Decoder joins by sequence, rejects incomplete groups.
- Z/B/C/K/W summaries contain standstill/startup peaks, cruise mean,
  saturation count/first time, speed-conversion error and sign/math counters.
- Nominal-sign mismatch is expected in intentional reverse-sign experiments.
  Configured-formula mismatch must remain zero in all four variants.
- Official Pigweed codec roundtrips all 9 rows with worst-case uint32 fields,
  <=32 bytes each; ARM ELF dictionary decode also passes. Log format strings
  are absent from the deployable BIN and present in the ELF dictionary.

For exact final full-rate statistics use the matching same-halt 128 KiB SRAM,
512 KiB Flash, A VTOR and exact ELF. The offline report accepts `--off-elf`
and `--on-elf` with receipt fields `ram_capture`, `flash_capture`, `vtor`,
`elf_sha256` (optional `ram_sha256`). It rejects mismatched Flash/ELF/VTOR.
The last periodic log need not include the final fraction of the run.

The record call has real instrumentation overhead. Old timing numbers must
not be relabeled as timing of these new images. Next board run must recheck
FOC max, 50 us misses and actual CCR late/margin with diagnostics enabled.

## Builds / regressions

`DECOUPLING_SIGN_TEST=OFF` and mode 0 by default. Nonzero mode without the
explicit A diagnostic opt-in is a configure/compile error. No automatic sweep
or live sign-switch command was added.

| Preset | Mode / Vd,Vq sign | Flash B | RAM B | Result |
|---|---|---:|---:|---|
| DqAuditCurrent | 0 / -, + | 221100 | 130008 | PASS |
| DqAuditReverseD | 1 / +, + | 221116 | 130016 | PASS |
| DqAuditReverseQ | 2 / -, - | 221116 | 130016 | PASS |
| DqAuditReverseBoth | 3 / +, - | 221124 | 130024 | PASS |

RAM linker region 131008 B: only 984 B remain in the largest variant. Preserve
the existing task-stack/runtime checks; link success is not stack qualification.
All variants have the same 13 preexisting unused/RWX warnings, no new warnings.

Audit-disabled A rebuilt in `build/DqAuditDisabledUnchanged`: Flash219300 B,
RAM129600 B. BIN is byte-identical to the previous board image:
`95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e`.

The preserved `FrictionBUnchanged` B build file remains unchanged (this is not
the same payload as the actually confirmed B916; see the follow-up report):
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.

71 related offline/host tests passed. Suites: dq helper/audit, CUR_CONFIRM, PWM pipeline, encoder
FOC-first, S-curve, acceleration FF, friction, identified current PI and intent
FSM. Tests also compare the expanded real FOC body after removing only the
new observer, plus the unchanged protection/IRQ owners.

## Next manual order — not executed

1. Use mode 0 with identical instrumentation to repeat OFF -> nominal ON,
   preferably another OFF/ON pair. Same initial rotor orientation, thermal
   state, calibration, recipe and existing safety settings; retain raw files.
2. Confirm stationary/first500ms terms, actual we conversion, configured math,
   common-vector saturation, FOC deadline and CCR margin before interpreting
   speed metrics. Do not compare separate query sequences as one frame.
3. Only if necessary and individually authorized, test reverse-D, reverse-Q,
   then reverse-both, each as its own bounded manual run. No automatic sweep,
   retry after protection or threshold increase. B remains the rollback.
4. Compare same-phase Vq/current/Id/start behavior and reproducibility, not
   just one peak or one OFF/ON mean. Do not select a new sign/PI/zero from
   insufficient evidence. Existing board runner pins the old image hashes;
   a new image needs its own reviewed staging identity, not blind hash substitution.

dq 解耦排查候选已就绪，等待人工板测。

File-only follow-up: [一次性离线收尾](dq-decoupling-deep-review-20261021.md),
including startup-metric interpretation, real-C PWM quantization sensitivity,
metadata parser fixes and the exact historical confirmed-B payload identity.
