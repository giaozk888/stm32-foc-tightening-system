# SPEED startup-integral and braking candidate, 2026-10-18

Implemented as the opt-in A/B preset `SpeedStartupBrakeTrial`, inheriting the
protected 20 rpm / 12 s loaded-FSM trial. Its profile response includes
`SPEED_CTRL=SB1`. No board operation, boot selection, firmware programming,
motor START or live recipe change was performed in this implementation turn.

## Scope and behavior

The recorded failure identifies an outer-speed-loop problem: after the
filtered speed passes the reference, positive speed integral continues to
outweigh proportional braking. The candidate changes the SPEED-mode integral
policy at 1 kHz. It does not redesign the complete cascade simultaneously.

1. Same-direction integral growth is limited to 0.20 A/s. This is a provisional
   command-shaping value for this candidate, not a tuned industrial constant.
   Integral unwinding and existing braking-direction integral are preserved.
2. The existing overspeed-I boundaries are reused: minimum speed magnitude
   5 rpm and error opposing rotation with magnitude at least 5 rpm. When the
   candidate integral still drives the overspeed direction, it is set to zero
   in that update. The P term can then command braking immediately instead of
   being cancelled by a slowly decaying positive integral.
3. Original +/-0.35 A integral clamp, +/-0.4 A SPEED output clamp and output
   saturation anti-windup still run after the candidate kernel.
4. No persistent controller state was added. Existing IDLE/mode-change resets
   remain in place. The kernel is used only for `MOTOR_MODE_SPEED`; POSITION
   settling, its speed-PI policy and active hold retain the prior behavior.

`FOC_SPEED_STARTUP_BRAKE` defaults OFF and requires the protected loaded-FSM
pipeline configuration. Ordinary profiles retain the old 5 A/s integral-bleed
policy. The old image captures and ELF used for fault analysis were preserved.

## Unchanged parts

Speed Kp=0.003 and Ki=0.020, 20 ms speed LPF, position-loop gains/logic, current
PI, Clarke/Park, SVPWM, PWM/ADC frequencies, electrical zero/direction/pole
pairs, one-cycle PWM pipeline, CUR_CONFIRM, TWO_SAMPLE and all current/speed
fault thresholds are unchanged. TighteningTask still owns the original
RUNDOWN/contact/settle/current-stage/HOLD sequence. No new work enters the
20 kHz ADC/FOC ISR and no ISR logging was introduced.

This change does not establish current-polarity/phase calibration, actual
torque accuracy, stopping energy or stable shaft-speed tracking. Those remain
board-validation questions.

## Offline evidence

The exact C kernel was compiled for the host at -Os and -O2. Six new tests
cover positive/reverse symmetry, bounded integral rise, preserved unwind and
braking integral, removal of stale driving integral, contact-current
reachability, original output/integral clamps, and real-fault-window replay.

The recorded old-policy output is reproduced to 1e-5 A. Replaying the same
recorded speed inputs with the new policy, including the old 0.236 A integral
history as a deliberately adverse initial state:

| Time, ms | Filtered rpm | Recorded old IqRef, mA | Candidate IqRef, mA |
|---:|---:|---:|---:|
| 707.838 | 26.06 | +214.25 | -18.17 |
| 723.875 | 59.14 | +34.97 | -124.82 |

This is counterfactual command replay with fixed recorded speed inputs. It is
not a closed-loop mechanical simulation or evidence that the new shaft speed
would follow that same curve or stay below the 60 rpm trip threshold.

A held-zero-speed test reaches the original 0.30 A contact-current threshold
at 1225 ms in both directions, within the existing 8 s rundown timeout. Thus
the integral-rate bound does not impose a permanent ceiling below contact
current. Mechanical contact detection itself is not qualified by this test.

Existing regressions also passed: pipeline (6 tests), loaded lease/register
mocks (1 test with 50 scenarios), CUR_CONFIRM (2 tests), TWO_SAMPLE audit
(4 tests). Total: 19 test methods passed. Original protected pipeline/mock
tests include output revocation, fault paths, stale feedback and one-cycle
commit behavior.

## Build results

| Slot | Flash / 229376 B | Flash free | RAM / 131008 B |
|---|---:|---:|---:|
| A | 229316 B | 60 B | 127944 B |
| B | 228308 B | 1068 B | 127928 B |

Both link successfully, with no new source warnings relative to the loaded
baseline. The pre-existing RWX LOAD-segment linker warning remains. A is very
close to its slot capacity; additional diagnostics will require a separate
Flash budget review rather than silently enlarging a partition.

BIN SHA256:

- A: `98a90620404a9daa1210f7f8e61aa9cbda6b8d612b8a884cc6d83a950e25f50f`
- B: `4ab7b29fa133cef38f34ef32107a5dd4f80629dc68f54b9f42696b56ca46988b`

New-image FOC wall/deadline/actual-CCR margins have not been measured on the
MCU. The previous 28.92 us result belongs to the earlier loaded B image and
must not be relabelled as this candidate's board timing.

## Main changes and reproduction

- `firmware_common/speed_startup_brake.h`: pure bounded-work integral guard.
- A/B `FOC_EncoderSpeedUpdate()`: optional SPEED-only application before the
  existing integral/output clamp and anti-windup commit.
- A/B CMake options/presets: separate opt-in image and configuration guard.
- `MOTOR TEST PROFILE`: version marker for the candidate.
- `tests/test_speed_startup_brake.py`: host C-kernel and fixed-trace replay.

Build with `cmake --preset SpeedStartupBrakeTrial` and
`cmake --build --preset SpeedStartupBrakeTrial` inside the chosen app folder.
Run `python -m unittest discover -s tests -p test_speed_startup_brake.py -v`.

The board remains stopped with the previously confirmed B634 and the original
A631 fallback. Candidate board validation is the next step; no motor restart
was included in this implementation.
