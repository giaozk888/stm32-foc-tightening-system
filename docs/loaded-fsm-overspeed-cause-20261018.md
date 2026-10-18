# Loaded-FSM overspeed diagnosis, 2026-10-18

This is an offline analysis of the single loaded B634 START attempt. Drive
12 V was subsequently confirmed OFF by the user. No device access, motor
commands, firmware builds or control/protection edits were performed for this
diagnosis.

## Finding

The direct control-side contributor is a positive speed-PI integral left over
from the long initial low-speed interval, combined with the existing 20 ms
speed LPF. The rotor feedback accelerates through the 20 rpm target while the
controller continues commanding positive Iq. At the last completed outer-loop
frame, filtered speed is 59.14 rpm but IqRef is still +34.97 mA. The next update
crosses the independent 60 rpm guard and closes the bridge.

This is not a missing state-machine stage or session timeout. The original
FSM remained in RUNDOWN throughout. Contact was not confirmed, so the later
seating/current/hold stages did not run.

## Exact retained window

The 32-row startup ring was frozen by the first CL_OVERSPEED fault. It contains
completed 1 kHz outer-loop frames at 692.878--723.875 ms after admission, plus
the separately captured fault frame at 724.844 ms. FSM elapsed time is sampled
at 100 Hz, hence the first-fault field reports 720 ms.

| Time after admission, ms | Instantaneous rpm | Filtered rpm | Speed P, mA | Inferred speed I, mA | IqRef, mA |
|---:|---:|---:|---:|---:|---:|
| 692.878 | 18.35 | 10.37 | +28.9 | +236.5 | +265.4 |
| 702.878 | 47.61 | 18.88 | +3.4 | +237.6 | +241.0 |
| 703.878 | 54.88 | 20.60 | -1.8 | +237.6 | +235.8 |
| 706.839 | 54.99 | 24.98 | -14.9 | +237.4 | +222.5 |
| 710.838 | 65.98 | 31.47 | -34.4 | +217.4 | +183.0 |
| 716.837 | 87.98 | 43.58 | -70.8 | +187.4 | +116.7 |
| 723.875 | 98.98 | 59.14 | -117.4 | +152.4 | +35.0 |

The P and I columns use the exact existing Kp=0.003 A/rpm and
`I = IqRef - Kp*(reference-filtered_speed)`. All these rows are SPEED mode,
below the +/-0.4 A command clamp, so the inference is applicable. They are
completed outer-loop frames, not the interrupted fault-frame context.

Existing code begins overspeed integral bleed when speed error magnitude is
at least 5 rpm and opposes rotation. For a 20 rpm target, positive rotation
starts this branch at filtered speed >=25 rpm. The existing 5 A/s bleed takes
about 47 ms to remove 0.237 A. The retained window shows this branch operating
exactly as coded; it does not make the torque command immediately braking.

The output-saturation anti-windup only applies when the +/-0.4 A output is
clamped. Commands in this window stay below 0.4 A. Consequently it does not
prevent this below-saturation startup integral accumulation. This should not
be described as an observed 0.35 A integral-limit saturation: the observed
integral is approximately 0.237 A before its release.

## Encoder/timebase checks

All 31 consecutive angle differences in the retained window are negative,
between -4 and -31 counts. With the configured ENCODER_DIRECTION=-1 this is
continuous positive mechanical feedback. Angles decrease from 1979 to 1453;
there is no 14-bit wrap crossing in this window. Sample timestamp differences
are 993--1008 us.

Replaying those differences and timestamps through the existing speed
conversion matches recorded instantaneous speed to <0.000008 rpm. Replaying
the existing 20 ms LPF matches filtered speed to <0.000002 rpm. Replaying the
existing speed-integrator update/5 A/s bleed matches the inferred integral to
<0.000000024 A. Encoder error and speed-glitch counters are zero.

Therefore a single isolated encoder outlier, wrap bug or compressed speed
timebase is not supported by this window. There is sustained, internally
consistent acceleration in the encoder feedback. An independent shaft-speed
measurement is still needed to rule out sustained magnetic/encoder error.
Zero parity errors alone cannot prove physical shaft motion.

The first-fault frame may mix the current speed update with the previously
published raw-angle/IqRef fields because the higher-priority protection
interrupt can preempt the outer-loop update. It is not used to infer one
additional angle delta or a speed-PI output for that same instant.

## Other paths

- FOC wall max 28.9176 us; deadline misses 0.
- Actual CCR commits 703151; late commits 0; minimum margin 15.1882 us.
- CUR_CONFIRM 314 enter / 314 clear / 0 fault.
- Current validator TRACKING at first fault; consecutive unresolved 0.
- Contact candidate duration 0 ms; contact stages never ran.

These exclude timing overrun, CCR late-write and CUR_CONFIRM/CURRENT_INVALID
as the reason for this stop. They do not independently qualify phase-current
polarity, electrical zero, phase-to-encoder alignment or torque accuracy.
One completed row contains an Iq outlier (-0.382 A); its isolated snapshot
cannot establish a sustained current-control fault.

## What remains unresolved

The preceding host telemetry shows low speed for roughly the first 0.6 s
while the current request rises. This explains how positive speed error had
time to accumulate, but the retained 32 ms window cannot identify why the
motor initially moved slowly. Mechanical/load resistance, electrical angle
or phase alignment, and actual drive-supply behavior remain candidates.

The next control-change investigation should address startup speed-integral
management and response when speed exceeds target, with the original
overspeed/current protections retained. It should not simply extend the
session again or raise the 60 rpm stop threshold. No such controller change
was implemented during this diagnosis.

## Reproduce

Run `python tools/analyze_loaded_fsm_overspeed.py`. The script verifies the
matching B image in the saved full-Flash capture and checks the ELF reset
vector before decoding RAM. It records input SHA256s, all 32 decoded rows and
numeric replay errors in ignored tmp/. The input prefix is
`loaded-fsm-motion-1792300223073650000`.
