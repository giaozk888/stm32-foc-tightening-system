# Bounded DOB feedback first OFF/ON board comparison

Candidate/source/test definitions:`docs/dob-feedback-candidate-20261023.md`.
Same frozen A219856B BIN9d4dae1bc55fb85fa5b821651ee0886e670644ad00ef3c77cd2923b3ce075aad,
ELFf1c61f2830ea1ca4046ef42d940a9e396737d0fd3cc9b63c92511bf1b0a6bc9a.
FormalB/boot/config not changed, no protection relaxation, no automatic retry.

## First OFF baseline completed

Fresh physical OFF/unloaded-unlocked-fixed-guarded/operator confirmation;
stage`tmp/mechanical-ident-stage-1792736217347768800.json` PASS two independent
full readbacks, B/boot/private/metadata unchanged, activationfalse,motor_commands0,
outputs off/CPUhalted. Separate fresh powered/no-alarm/operator confirmation;
one600rpm OFF run only, original5s drive/deceleration/12s lease and protection.

Run:`tmp/mechanical-ident-run-1792736271628104000.json`;
batch:`tmp/mechanical-ident-batch-1792736271546559200.json` PASS safe acquisition.
Stopped RAM SHA02411c0239fc3f83bcd5e51cf0062d1e2d424304ff161f597be16f311bbe50b8.

- Power-off calibration/compute/timing/readiness preflight PASS. Task free
  stack2516B. Manual FB CFG exactly ON0/gain250000ppm/cap25000uA/fraction50000ppm/
  slew250000uA/s/fresh2000us/hold5000us/zero20000us. No ON command sent.
- Runtime reports FEEDBACK0/DOB_CONTROL0; saved80Bfeedbackstate enabled0,
  compensation0,peak0, GOOD/HOLD/FADE/CLEAR/CLAMP0.8030outerupdates.
- Whole DOB6394/8030valid=79.6264%,303selector rejects. Not steady validity.
- Speed FF stats:acceleration MAE22.2510700/3.1999400=6.95359rpm;
  deceleration MAE19.8811092/3.0300016=6.56142rpm;
  maximum instantaneous trackingerror63.19430rpm, overshoot5.67010rpm.
- Positive cruise MAE4.5739942/1.7999982=2.54111rpm; low-speed MAE
  2.2855892/.18601321=12.28722rpm; stable-motion start criterion393.047ms.
  This is the existing stable-motion criterion, not raw physicalfirstmotion.
- Iq commandpeak.4254929A; PIpeak.3111179A; integratorpeak.1332453A;
  saturationtime0. Existing instantaneous dq measuredpeak1.2372286A includes
  unscreened raw/control-path samples in old stats; not a calibrated load or
  proof of realphase overcurrent. DOB-only filtering does not alter this path.
- No independent motor fault. FOCwallmax33.2411765us,deadline0,CCRlate0,
  mincommitmargin15.1294118us. Estimator stats are not current injection.

STOP/ANALOG SAFE and full stoppedFlash/RAM captured before analysis. User
confirmed physical12V OFF. Restore
`tmp/mechanical-ident-restore-1792736349562276800.json` PASS: originalB preserved,
B application NOT run, motor_commands0, outputs off/CPUhalted. Same-image ON
preparation follows only while12V remains OFF; no automatic powered ON run.

Same-image preparation PASS:
`tmp/mechanical-ident-stage-1792736403239859100.json`. No flash programming
needed (existingA identical); two independent full readbacks, B/boot/private/
metadata unchanged, activationfalse,motor_commands0,SD/MOE/PWMoff,CPUhalted.
Separate powered/no-alarm/operator confirmation is required for one ON run.

## ON comparison completed, no speed-tracking improvement established

Separate fresh powered/no-alarm/operator confirmation received. One600rpm
run only with `--feedback-on`; no retry or parameter change. Run
`tmp/mechanical-ident-run-1792736471931434600.json`, batch
`tmp/mechanical-ident-batch-1792736471841729900.json` PASS safe acquisition.
Stopped RAM SHA474f732a27e360974bfe31b1217d87d01a5d04a5c0890f93847a8b0ec4c02385.

Manual FB CFG initiallyOFF, guardedON accepted before RUN, subsequent model/
direction/admission/runtime views report FEEDBACK1/DOB_CONTROL1 and unchanged
gain.25/cap25mA/fraction5%/slew.25A/s/fresh2ms/hold5ms/zero20ms. Mode claims
are independently supported by saved80Bfeedback state and runtime samples,
not just an enabled compile flag. Actual compensationpeak5.6587653mA, under
cap, clampcount0.7940updates,6200fresh valid estimator consumptions,506hold
updates and30fade updates; these are update COUNTS, not event counts or exact
durations. No full applied-compensation waveform was retained, so exact maximum
slew/gap behavior is proven offline, not retrospectively from sparse UART.
Stopped compensation0/have_valid0/STATEWAIT; runtime ON flag remains selected
in halted A RAM but cannot actuate; physical B selection is restored below.

|Metric|OFF|ON .25gain|
|---|---:|---:|
|Acceleration speed MAE rpm|6.95359|8.44086|
|Deceleration speed MAE rpm|6.56142|6.84594|
|Cruise speed MAE rpm|2.54111|2.66919|
|Low-speed MAE rpm|12.28724|12.35389|
|Maximum instantaneous speed error rpm|63.19430|83.51329|
|Overshoot rpm|5.67010|5.33875|
|Iq command peak A|.425493|.413101|
|Speed PI output peak A|.311118|.298726|
|Speed integrator peak A|.133245|.114711|
|Iq saturation seconds|0|0|
|Existing stable-motion delay ms|393.047|250.042|
|FOC wallmax us|33.24118|33.27647|
|Deadline miss / CCR late|0/0|0/0|

This single OFF/ON pair shows worse primary acceleration/cruise tracking,
despite lower overshoot/PI/integrator/Iqcommand peaks. It does NOT establish
causality, repeated significance or loaded-disturbance rejection. Start
confirmation differed BEFORE fully warmed DOB could necessarily contribute;
do not credit its393->250ms change to feedback. The first retained nonzero
feedback sample is US9356362, COMP-59uA, then US9732378 COMP521uA and
US10132329 COMP1599uA. UART is sparse/sequential, not a first-onset detector.
No deliberate external load was applied. Do not enable stableB based on this.

ONwhole DOB6200valid/7940observations (~78.09%); selector291/7566quarantined,
280recoveries,no longgap reset,no confirmedId event. Motor protectionfault0;
CUR_CONFIRM enter152/clear152/fault0,max2cycles101us. Taskfreepreflight2480B,
FOC33.27647us,deadline0/CCRlate0. Existing unscreened instantaneous measuredIq
peak1.392889A is distinct from.413101A command peak and5.6588mA DOBcomp peak;
do not equate this stat to a validated physical phase-current overcurrent.

After STOP/ANALOG SAFE, full stoppedFlash/RAM captured and CPUhalted. User first
replied with ambiguous typo, so no reset/restore was done until a second clear
`关了` physical12V OFF confirmation. Restore
`tmp/mechanical-ident-restore-1792736567554269700.json` PASS: originalB/boot/
private/config preserved, B application NOT run, motor_commands0,outputs off,
CPUhalted. No further motion, no automatic gain increase or promotion to B.
