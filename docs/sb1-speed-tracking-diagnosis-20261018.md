# SB1 speed tracking diagnosis: saved evidence only

No board access, reset, START, parameter/threshold or controller modification
was performed in this diagnosis. It reads the exact stopped speed-test receipt,
full Flash, RAM and matching A ELF. The previous recovery remains unchanged:
confirmed B649, SD/MOE/CCER off, halted before B application instructions.

## Important correction: UART missed the real peak

UART's32 status replies contain a maximum filtered speed17.8rpm. That is NOT
the maximum of the running1kHz speed loop. The existing retained SPEED-only
diagnostics in RAM are not cleared by the ordinary IDLE/STOP path:

| SPEED-mode retained statistic | Value |
|---|---:|
| Valid | 1 |
| Integrated SPEED execution time | 2.01604s |
| Minimum filtered speed | -0.66607rpm |
| Maximum filtered speed | **31.03976rpm** |
| Time-weighted mean filtered speed | 1.49852rpm |
| Integrated angle from speed | 18.12647deg |

The time-weighted1.50rpm is for the complete SPEED interval. The earlier0.4rpm
figure was only the UART samples in the final0.5s; they are different scopes.
The speed integral is consistent with the approximately18degree position
change. It is still encoder-derived, not an independent tachometer reading.
The recorded maximum is about55.2% above20rpm, but below the unchanged60rpm
protected-profile overspeed trip. Therefore no fault is entirely consistent
with a substantial short overshoot.

## What explains the command collapse

The exact SB1 kernel has two relevant policies:

1. Positive driving integral can rebuild at most0.20A/s. At20rpm error, the
   original Ki would add about0.40A/s, so SB1 commonly caps that growth.
2. At forward speed at least5rpm, error at most-5rpm and positive driving
   integral, it replaces that integral with0 in the same update. With a20rpm
   reference, the speed boundary is25rpm, not the60rpm protection trip.

These are command-shaping boundaries, not changed protection thresholds.

The same run's UART observations are:

| Time,s | Filtered rpm | Iq reference,mA | Inferred speed integral,mA |
|---|---:|---:|---:|
| 1.123 | 0.2 | 275 | about215.6 |
| 1.248 | 14.7 | 255 | about239.1 |
| 1.307 | 17.8 | 1 | about-5.6 |
| 1.367 | 1.6 | 62 | about6.8 |
| 1.986 | 0.3 | 190 | about130.9 |

For those settled-reference SPEED samples, the inference uses
`I = IqRef - 0.003*(20 - filtered_rpm)`. UART rounding and asynchronous task
sampling mean the inferred values are approximate, not exact stored PI states.

The31rpm retained maximum crosses the25rpm reset boundary. The large loss of
positive integral, near-zero Iq command and subsequent0.20A/s rebuild strongly
support this sequence:

current builds while movement is poor → brief breakaway/acceleration → SB1
removes driving integral → little sustaining current/braking → speed collapses
→ current slowly rebuilds.

This is not the old failure where positive stored integral kept driving an
overspeed. The new policy suppresses that stored drive but appears too abrupt
for this low-speed operating point. The exact peak/reset frame was overwritten
by the32-frame ring: reset count and every1kHz integral state during that event
were not captured. This is a well-supported causal interpretation, not a
frame-by-frame direct recording of the reset instruction at31rpm.

## Tail replay: current loop not wholly excluded or certified

The immutable startup ring holds2015 completed outer-loop frames in total but
only the final32 are retained:1983.919..2014.914ms. It does not hold the
1.2..1.35s breakaway window. Replaying successive saved raw angles, timestamps,
20ms LPF and existing SB1 integral update gives:

| Tail result | Value |
|---|---:|
| Encoder sample interval range | 995..1006us |
| Raw speed replay max error | 0.00000191rpm |
| LPF replay max error | 0.000000148rpm |
| Iq reference replay max error | 0.0000000247A |
| Mean Iq command | 0.195905A |
| Mean measured Iq | 0.190722A |
| Mean Iq error | -0.005183A |
| Iq error RMS | 0.054394A |
| Mean Id | -0.000720A |
| Mean Vq | 0.140910V |

The average current is near the command in this SHORT tail under the SAME
current sensor/electrical-angle model. Its54mA RMS error is material relative
to a196mA command. This is not proof of clean current feedback, correct phase
mapping/polarity, correct electrical zero or reliable torque production.
No full-breakaway current/voltage window exists to decide those questions.

## Classification and next design direction

Established: no new zero failure, no fault, no50us deadline miss, no late CCR;
peak speed was31.04rpm, and startup/tracking were unsatisfactory. There is no
evidence requiring further FOC math/timing optimization for this response.

Strongly supported: the SB1 driving-integral reset plus slow rebuilding makes
the already sluggish/bursty startup harder to sustain. Simply raising a fault
threshold or running the same failed pattern longer is not a diagnosis/fix.

Unresolved: why near-zero speed persists until approximately0.28A command.
Possible categories include mechanical resistance/cogging, electrical angle or
phase alignment, current feedback/torque conversion, and supply behavior. The
capture contains neither independent torque nor instantaneous supply voltage/
current-limit state at breakaway, so none is asserted as the sole cause.

A subsequent change should consider bumpless, bounded integral unloading/
restoration (rather than unconditional zeroing of all driving integral), and
capture the breakaway/first overshoot1kHz window to verify it. It must retain
hard overcurrent, overspeed, CURRENT_INVALID/CUR_CONFIRM, PWM pipeline and
existing output clamps. No such code change or new motor test was done here.

## Reproduction

- `python tools/analyze_sb1_tracking.py`
- `python -m unittest discover -s tests -p test_sb1_tracking_analysis.py -v`
- Output: `tmp/sb1-tracking-analysis-20261018.json`
- Source receipt: `tmp/sb1-speed-speed-1792310227239040200.json`

The decoder validates exact image/ELF/full-Flash identities and native ARM
symbol sizes before interpreting RAM, and refuses a nonmatching capture.
