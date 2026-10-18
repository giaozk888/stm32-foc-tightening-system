# SB2: bounded SPEED integral unload/rebuild candidate

## Scope

This implements the identified SB1 software-policy correction. It is not a
claim that the motor's complete low-speed mechanical response is fixed.
The original reason for poor initial movement at about0.28A remains unproven.
No board access, firmware programming, reset, START or boot-selection change
was performed in this implementation turn. B649 remains the last recorded
selected, stopped image. Historical SB1 images and their matching ELF/captures
are retained for comparison and decoding.

New A/B preset: `SpeedBumplessTrial`, inheriting `ZeroValidAdmissionTrial`.
New opt-in flag: `FOC_SPEED_BUMPLESS=ON`, defaultOFF. Requires the complete
protected loaded-trial, startup/brake, one-cycle pipeline and valid-zero profile.
Its UART profile marker is `SPEED_CTRL=SB2`; old SB1 runners cannot silently
accept it as their pinned SB1 image.

## Changed SPEED behavior

Only the1kHz SPEED integral shaping is replaced. There is no new persistent
controller state, learned torque bias, observer, lookup table, heap or ISR log.

| Policy | SB1 | SB2 candidate |
|---|---|---|
| Existing overspeed-error boundary | 5rpm | unchanged |
| Existing minimum speed for release | 5rpm | unchanged |
| Driving integral above boundary | zero in one update | unload by at most10A/s, stopping at0 |
| Same-direction I rebuild cap | 0.20A/s | 0.40A/s, never above original PI candidate |
| Already-braking integral / ordinary unwind | original policy | original policy |
| Current output limit | ±0.4A | unchanged |
| Integral clamp | ±0.35A | unchanged |
| Speed Kp / Ki | 0.003 / 0.020 | unchanged |

At a1ms update, unloading is bounded to10mA and driving-I growth to0.4mA.
For the observed approximately239.1mA integral and31.04rpm speed, the next
candidate integral is229.1mA, not0 and not224.1mA. The legacy5mA bleed must
not be subtracted a second time.

The10A/s release is a provisional compromise between the old5A/s unloading
(which left positive drive in the earlier59rpm fault window) and SB1's
single-update approximately240mA reset. At sustained overspeed, it takes at
least24ms to remove0.24A. The0.40A/s rebuild matches original Ki×20rpm at
zero speed and is still capped by the original PI's computed candidate; it
does not fabricate extra feedforward torque. These are command-shaping rates,
not new current/overspeed protection thresholds or industrially tuned constants.

When speed re-enters the existing error boundary, normal integration resumes
from whatever I remains. If overspeed persists, driving I reaches0 and ordinary
braking integration can continue; no saved high torque is reloaded later.
This reduces the abrupt-reset/restart failure mode but can still produce
short positive Iq while unloading. It does NOT guarantee immediate braking,
absence of overshoot, reliable breakaway or stable motor speed. Board response
must be measured before motor-control acceptance.

## Production integration details

`SpeedBumpless_Apply()` is a fixed-work, inline helper in
`firmware_common/speed_bumpless.h`. A/B `FOC_EncoderSpeedUpdate()` calls it only
for `MOTOR_MODE_SPEED`, before the existing integral/output clamps and original
anti-windup commit. The old SB1 path remains under the opposite compile branch.

`sb2_previous_A` is captured AFTER mode-transition reset, BEFORE the legacy
overspeed block can mutate `speed_integrator_A`. SB2 uses that original value
to produce its bounded unload; its unload flag ensures the normal commit
stores the final result. This avoids both double subtraction and reuse of a
preceding mode's integral. Existing IDLE/STOP/fault initialization remains the
owner; no new state can restore stale PWM or torque after those transitions.

POSITION and active-hold integral policy are not changed. Current-loop
Clarke/Park/PI/SVPWM, direction, pole pairs, electrical zero, ADC/PWM frequency,
CURRENT_INVALID, current discriminator, CUR_CONFIRM, hard-overcurrent, speed
trip, current/output clamps, PWM pending pipeline, IRQ priorities, zero sample
admission, tightening and CAN/Pigweed/IAP/A-B logic are unchanged.

Preprocessed-function equality tests verify the complete compiled source of
`FOC_CurrentLoopStep`, `ProtectedLoop_PwmEntry`, `ProtectedLoop_Pair`,
`ProtectedLoop_SetDuty`, `ProtectedLoop_AdcIrq`, `FocCurrentValidation_Push` and
`TighteningTask` between SB1 and SB2, for both slots. This is stronger than a
comment or a changed-file list, but does not replace new MCU timing measurement.

## Build and targeted verification

| Slot | Flash bytes /229376 | Flash free | RAM bytes /131008 |
|---|---:|---:|---:|
| A SpeedBumplessTrial | 228500 | 876 | 127960 |
| B SpeedBumplessTrial | 227484 | 1892 | 127944 |

Compared with robust-zero SB1: Flash+72B, no RAM growth. MotorControlTask's
compiled static stack use remains208B. Existing unused-function/variable and
RWX LOAD-segment warnings remain; ARM syntax-warning set comparison shows no
new warning. No warning was suppressed.

13 targeted test methods PASS, executing the actual C helper at both-Os and-O2:

- measured operating-point unload and no legacy/SB2 double subtraction;
- symmetric release/recovery and exact5rpm boundary;
- surviving-I recovery without exceeding the original PI candidate;
- preservation of already-braking I and ordinary unwinding;
- sustained overspeed still removes driving I, never automatically reloads it;
- a CONSTRUCTED short peak using measured31.04rpm retains some I;
- existing contact-command reachability and unchanged±0.35/±0.4 clamps;
- original mode reset cannot resurrect state (helper has no persistent state);
- exact recorded old-overspeed input replay still reproduces the old output,
  while SB2 has negative final Iq and bounded inter-step I changes;
- exact A/B profile identity/size, historical A image hash preservation;
- preprocessed frozen-function equality and no added ARM source warnings.

The counterfactual uses the SAME recorded speed inputs. It is not a plant
simulation and cannot predict the shaft speed with different Iq commands.
The constructed short-peak case is not the missing real1kHz peak waveform.

Commands:

`cmake --preset SpeedBumplessTrial`

`cmake --build --preset SpeedBumplessTrial --parallel 6`

`python -m unittest discover -s tests -p test_speed_bumpless.py -v`

Build inside each app directory. Targeted log: `tmp/sb2-focused-tests.log`.
The full historical-suite result is recorded below after completion; unrelated
old pins/assertions are not changed to manufacture an all-green result.

Full discovery completed: **1148 tests,1135 passed,9 failures and4 errors**.
The13 failing/error test names are the same as in the prior robust-zero full
suite, covering unavailable/private or mismatched historical evidence, old
source-layout/hash assertions and the legacy extracted-loop fixture. They
remain unresolved; no assertion or old image pin was relaxed. This is not an
all-green full suite. Log: `tmp/sb2-all-tests.log`.

That discovery began before the final preprocessed-equality test was added,
so it collected12 SB2 test methods. The separate final focused run collected
and passed all13, including that equality check. Existing SB1, robust-zero,
CUR_CONFIRM and PWM pipeline cases passed in the full run.

Final BIN SHA256:

- A: `b78864f64ff417d4cfc3101f9d6f22292a96e89807359f4154aa8ee6ba0f8488`
- B: `99e15d9e25c0aeade7dd57617dcd394dd007f1cbc05c652719ab7f63be1eba18`

The new SB2 timing is **not yet measured on MCU**. The earlier28.92us and
15.18us actual margin belong to SB1 and must not be relabelled as SB2 results.

## Next acceptance, not performed here

Use the SB2 image and a separately pinned no-load test runner. Re-check normal
supply zero and current FOC/actual-CCR timing first. Only a fresh human-authorized
motor trial can establish whether breakaway, the retained1kHz peak, sustained
speed and STOP response improve. The existing32-frame tail misses the early
peak, so a subsequent capture should preserve the first release/overshoot
context rather than relying on sparse UART maxima alone. This implementation
does not silently change that diagnostic ring or add20kHz work.
