# Candidate A bounded low-gain DOB feedback

User requested trying feedback after the200mA shadow test. This is NOT a
promotion to stableB, not a verified load-rejection result and not permission
to increase any motor safety/current/voltage limit. The new candidate defaults
runtime OFF and requires an explicit guarded manual ON command while idle and
SD/MOE/AOE/CCER are all OFF. First trial is same-image OFF baseline; a later
fresh operator confirmation is required for ON. No automatic OFF/ON sequence.

## Formula, units and sign

Original observer and its identified normalized mechanical model are unchanged:

`J/Kt * omega_dot = Iq - B/Kt*omega - Ic*sign(omega) - bias - d_load`.

Positive residual is extra resisting load in equivalent A, so the new adapter
uses `iq_dob = +.25 * d_hat`. This is not a new friction offset or replacement
for speed PI. Compensation is capped by
`min(.025A, .05*current_iq_limit)` and changes at at most`.25A/s` during tracking
and re-entry. Negative disturbance produces negative compensation; no abs/sign
substitution or motor-direction change.

`iq_pi = P + committed_integral`

`iq_raw = ((iq_pi + iq_acc_ff) + iq_friction) + iq_dob`

`iq_ref = clamp(iq_raw, -iq_limit, +iq_limit)`.

The original conditional/partial integration rule is retained but includes all
three feedforward terms at the saturation boundary. Release/bleed retains its
original priority. No DOB addition after the total clamp. OFF/zero compensation
calls original `SpeedFriction_Apply` exactly, preserving original numerical
outputs. Current PI, speed gains, S-curve, Ka, friction, BEMF, observer/model,
200mA pre-LPF policy,60mA/20ms Id gate, PWM/ADC/angle/IRQ/safety are unchanged.

## Temporal adapter and ownership

The1kHz speed owner consumes the previous completed task observer frame; the
existing non-control observer still runs AFTER real angle publication and ACK.
No early watchdog ACK, no new ISR work, no replay of excluded current samples,
no modification to actual FOC feedback. Running/armed/no-fault speed mode is
required. Valid finite estimate must be<=2000us old. Invalid or stale data
cannot refresh `last_valid_us`: hold ACTUAL applied compensation up to5ms age,
then fade to0, no later than20ms. Re-entry slews from actual remaining value,
not an instant restored estimate. OFF/STOP/not-running/fault/bad outer dt clears
compensation; original independent fault shutdown remains authoritative.

The validity percentage alone never enables feedback. Status, source time,
limits and lifecycle are checked every speed update. The model/filter state
is not reset by this adapter; estimator quality and control adapter are separate.

## Files and diagnostics

- New `firmware_common/dob_feedback_candidate.h`: bounded temporal adapter and
  total-output speed-sum/AW helper;80Bstate, no dynamic allocation.
- New `firmware_common/dob_feedback_binding.inc`: separate guarded task command
  adapter; original observer files remain free of critical sections/actuator
  access. Runtime switch changes no actuator and does not start a motor.
- `firmware_common/mechanical_dob_binding.inc`: readonly observer dispatch plus
  optional adapter routing; FEEDBACK flag reflects selected candidate mode.
- `firmware_common/friction_calibration_binding.inc`: direction view truthfully
  reports candidate `DOB_CONTROL` selection.
- `foc2_app_a/Core/Src/main.c`: task-speed summing junction only.
- `firmware_common/protected_closed_loop.inc`: clear adapter on inactive/fault
  lifecycle, no changes to guard/ISR/protection decisions.
- A CMakeLists/Presets: opt-in `MechanicalDobFeedbackCandidate`, not default B.
- New native/tests and `tools/dob_feedback_board.py` hash-pinned single-point
  supervised OFF/ON harness; files-only by default, actual prior B1079 proof.

UART: `MOTOR TEST MECH DOB FB ON|OFF|CFG|STATUS|SUM|STATS`.
CFG reports gain/cap/fraction/slew/fresh/hold/zero bounds. STATUS records
timestamp/mode/state/last-good age/estimate/actualcomp. SUM records timestamp,
PI/raw/ref/integrator/saturation. STATS records updates/fresh-good/hold/fade/
clear/clamp counts and compensation peak. Replies split to remain within192B;
sequential STATUS/SUM must not be treated as same-frame unless US matches.
Counters/current state also saved in stopped RAM. Existing speed/FF/friction/
FOC timing/ADC/Id trace and stopped fullFlash/RAM capture remain.

## Build and offline evidence

A build PASS, BIN219856B; static RAM130784/131008B,224B remaining, no stack/heap
shrink. Existing unused-function and RWX warnings remain. Review B builds PASS
and its BIN hash unchanged:
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
PhysicalB is not rebuilt/flashed by the hardware script.

A BIN SHA256`9d4dae1bc55fb85fa5b821651ee0886e670644ad00ef3c77cd2923b3ce075aad`;
ELF SHA256`f1c61f2830ea1ca4046ef42d940a9e396737d0fd3cc9b63c92511bf1b0a6bc9a`.
This image is frozen for board provenance; do not rebuild in place after stage.

Production adapter/helper tests at-Os/-O2 with-Wall/-Wextra/-Werror PASS:
runtimeOFF, both-sign step, magnitude/slew, invalid hold/fade/expiry, re-entry,
stale/NaN, lowerdynamicIqcap, STOP/not-running, clockwrap,30k randomized exactOFF
comparisons and total sum/clamp checks, total-output-only saturation/AW on
bothsigns, analytical resisting-load compensation sign. Protocol tests cover
all busy/output guard conditions, truthful feedback flags, commandprefix,
extreme-value reply capacity. Preprocessed FOC/current/angle/PWM/guard/power/
readiness functions compare identical; only speed summation and adapter
lifecycle differ. These are synthetic/offline checks, not closed-loop stability
or physical load rejection validation.

Related regression initially211tests across44separate modules:210PASS and one
source-level readonly-observer invariant detected critical sections being
placed in the observer binding. Rather than relax the test, moved feedback
command adapter to its own include; reran all5observer tests and all3feedback
tests PASS. All211reviewed tests now pass across original run plus repaired
module rerun. Four new board-harness tests also PASS (215unique tests total):
files-only identity/priorB1079, fresh physical gates, wrong gain/failed ON
cannot RUN, RAMbounds/mode validation. No physical feedback result inferred.

## First manual board comparison

1. Fresh physical12V OFF/operator/setup confirmation; write inactiveA only,
   full independent readbacks, preserve stableB/boot/config.
2. Separate powered/no-alarm/operator confirmation. Original calibration,
   power-off compute/timing/stack/readiness preflight; failure means no RUN.
3. One +600rpm, feedback OFF baseline with original limits/lease/deceleration.
   STOP/ANALOG SAFE, fullFlash/RAM capture and halt before analysis.
4. Operator confirms12V OFF; restore B selection without running B. Compare
   baseline speed errors/Iq/integrator/timing and confirm compensation peak0.
5. New operator confirmation for the same-image ON point. Repeat preflight;
   explicitly guarded ON(.25gain) before one600rpm RUN. Abort on any independent
   protection, no retry and no higher gain/current. Capture/stop/restore as above.
6. Compare speed MAE/accel/decel/overshoot/Iq/integrator/saturation, comppeak,
   dropout behavior and FOC deadlines/CCR. Unloaded single trials do not establish
   calibrated torque accuracy or load-disturbance rejection; do not promote B.
