# DOB gain0.15 candidate A / three600rpm ON trials

User requested gain0.15 after gain0.5 three-run comparison. Continue600rpm,
three ON runs. Only A-only diagnostic feedback scalar changes; formal stable B
is not modified. Same Iq total limit +/-0.50A, DOB cap min(0.025A,0.05*IqLimit),
slew0.25A/s, source freshness2ms, hold5ms, zero20ms. Current/speed PI,
Ka0.000046875 A/(rpm/s), friction, BEMF, observer model and quality logic,
FOC/PWM pipeline, ADC/encoder, IRQ priorities and all protection unchanged.

## Build and offline checks

New preset `MechanicalDobFeedbackGain015Candidate` inherits original feedback
candidate, selects only `DOB_FB_GAIN=0.15f`, rejects conflicting gain profiles.
Runtime feedback still defaults OFF. UART gain must read150000ppm before RUN;
old250000/500000/1000000 config rejected by harness.

A build PASS, BIN219860B; RAM130784/131008B, no stack/heap shrink.
BIN SHA256 ee8481cdae09e92b4c4417a542be2f08580013a0f88e0aef4cd6acdae06f1fee
ELF SHA256 dede33e009586b7aaae384d76369e523b943d3ef735635ab7d67e783bd0a8a99.
Freeze these artifacts after staging. Prior0.25/0.5/1.0 builds not rebuilt.
Review B has no build work; BIN hash unchanged:
7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366.

Five new tests PASS: real native helper at-Os/-O2 (signed20mA ->3mA feedback,
unchanged cap/slew/freshness/hold/fade/STOP/total-output AW), preprocessed
protected FOC/control/power/angle/task/readiness bodies identical to gain0.5,
frozen previous BIN; files-only current image/actual prior B1099 receipt;
fresh physical gates, wrong-gain blocks; exactly3ON runs with explicit0.15
metadata and stop-on-independent-protection/no retry. Related regression
results:163/163 PASS across38 individually run modules, recorded in
`tmp/dob-feedback-gain015-regressions.log`. Offline mocks are not board proof.

## Board plan and authorization

User separately confirmed12V OFF, MCU powered, shaft unlocked, unloaded/fixed/
guarded, unchanged wiring,12V/.5A supply, whole-three operator present with
immediate power cut. Only inactiveA may be staged, preserve B/boot/private/
configuration and verify two independent full readbacks. Separate fresh
powered/no-alarm confirmation before activation; original calibration,
output-off/timing/stack/readiness checks before each authorized600rpm RUN.
Same5s drive/deceleration,12s board lease,1000rpm trip/30000degree travel.
Protection/transport/readiness/closure failure stops whole batch; no retry.
Save stopped Flash/RAM after every run. Ask physical12V OFF before restoring
original B selection; do not run B. No automatic gain adoption or promotion.

## Files

- foc2_app_a/CMakeLists.txt and CMakePresets.json: opt-in0.15 scalar selection.
- tools/dob_feedback_gain015_board.py: frozen image identity, validates prior
  actual gain0.5/B1099 baseline before installing0.15 identity; reuses existing
  reviewed three-run executor, closure/capture and protection workflow.
- tests/test_dob_feedback_gain015.py and test_dob_feedback_gain015_board.py.

Compare acceleration/cruise MAE, overshoot, command/integrator peaks and actual
DOB compensation to historical OFF/.25/.5/1.0 as noncontemporaneous reference,
not randomized paired A/B or proof of load-disturbance rejection.

## Staged, not activated

Stage `tmp/mechanical-ident-stage-1792739653323506300.json` PASS after fresh
physicalOFF confirmation: new inactiveA written, two independent full
readbacks verified, B/boot/private/metadata unchanged, activationfalse,
motor_commands0, outputsOFF and CPUhalted. Separate powered/no-alarm/whole-
three operator confirmation remains required before activation or motion.

## Three gain0.15 ON trials completed

Fresh powered/no-alarm/whole-three operator confirmation received. Batch
`tmp/mechanical-ident-batch-1792739737079834400.json` PASS, exactly3/3 runs,
no retries. Actual UART GAIN_PPM150000 verified in each run, runtimeOFF then
guardedON; original calibration/output-off/timing/stack/readiness passed.
Each run saved stopped full Flash/RAM and observer/controller/adapter evidence.

|Run receipt `mechanical-ident-run-...json`|Acceleration MAE rpm|Cruise MAE rpm|Overshoot rpm|Applied DOB peak mA|
|---|---:|---:|---:|---:|
|1792739737163657800|8.43917|2.91384|6.02069|6.07759|
|1792739781076131100|7.59152|2.98508|5.53412|2.45891|
|1792739811534680700|7.83153|3.83453|6.56793|5.81440|

## Mean +/- sample SD and historical reference

|Metric|Earlier OFF5|Earlier gain0.25 ON5|Earlier gain0.5 ON3|Current gain0.15 ON3|
|---|---:|---:|---:|---:|
|Acceleration MAE rpm|7.70189 +/- .91774|7.52873 +/- .88978|7.96618 +/- .48512|7.95407 +/- .43691|
|Cruise MAE rpm|2.25717 +/- .16145|2.25699 +/- .24240|3.08286 +/- .53967|3.24448 +/- .51224|
|Overshoot rpm|5.51954 +/- .40799|5.72614 +/- .52409|6.00667 +/- .47506|6.04091 +/- .51720|
|Iq command peak A|.416593 +/- .015507|.421877 +/- .013797|.428295 +/- .015461|.406258 +/- .033158|
|Integrator peak A|.124594 +/- .012203|.129827 +/- .009515|.131745 +/- .013652|.124531 +/- .014322|
|Applied DOB peak mA|0|4.86174 +/- .90492|7.73780 +/- 1.95762|4.78363 +/- 2.01757|

Current deceleration MAE7.50695 +/- .49001rpm; whole-observation DOB valid
fraction .784397 +/- .008375. Stable-confirmation delay .337678 +/- .084479s
is NOT first physical motion and is not used as the primary ranking metric.
Iq saturation seconds0 and feedback clamp updates0 in all3. Largest actual
compensation6.07759mA and commandpeak.437090A remain below unchanged25mA/.50A
limits; no recorded current clamp explains differences.

Gain0.15 mean acceleration error is essentially unchanged from0.5; cruise
error and overshoot are slightly higher. It does not improve the earlier
gain0.25/OFF mean tracking numbers. Historical cohorts are noncontemporaneous,
unequal in size, with run variation: they do not isolate a causal gain effect,
establish statistical significance, or test load-disturbance rejection.
No automatic gain selection, parameter write or formal B promotion.

## Timing and stopped condition

All3 firstfault VALID0, deadline miss0, CCR late0. Worst FOC33.49412us,
minimum commit margin14.46471us, minimum preflight task free stack2464B.
Feedback valid update counts6152/6282/6289, holds578/560/500, fades30/28/35;
counts are not independent events or exact durations. Captured applied
compensation returned to0 and all runs ended outputsOFF/CPUhalted.
User separately confirmed physical12V OFF before restoring original B.
Restore `tmp/mechanical-ident-restore-1792739878657774600.json` PASS:
original B/boot/config/private unchanged, B application not run,
motor_commands0, metadata sequence1103 selects B, VTOR0x08040000,
SD/BDTR/CCER0, CPUhalted. CandidateA not promoted; no further motor run.
