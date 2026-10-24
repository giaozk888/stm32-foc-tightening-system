# DOB feedback gain0.5 candidate A / three600rpm ON trials

User requested0.5gain and three tests, following.25ON5/OFF5 and1.0ON3 trials.
Only the DOB feedback scalar changes. No PI/Ka/friction/BEMF/model/observer
bandwidth/current/voltage/phase/ADC/IRQ/PWM/protection change; no stableB update.

New opt-in `MechanicalDobFeedbackGainHalfCandidate` inherits feedbackA with
`DOB_FB_GAIN=0.5f`. CMake rejects simultaneoushalf/one settings and requires
feedbackdiagnostic. Previous.25/1.0 firmware artifacts remain frozen. Same
`iq_dob=.5*d_hat`, compensationcapmin(.025A,.05*IqLimit),.25A/s tracking/reentry,
2msfreshness/5mshold/20mszero; PI+accFF+friction+DOB jointly limited by±.50A
and total-output AW. Runtime defaultsOFF; only guarded idle/output-off ON.

Production edit limited to A CMakeLists/Presets selecting scalar. Existing
shared gain native test is parameterized without relaxing its assertions;
three-run harness metadata/imageflag checks made scalar-aware,1.0default
unchanged. New `tools/dob_feedback_gainhalf_board.py` preserves original
gain1/B1095 receipt identity BEFORE selecting new.5 hashes, then reuses the
reviewed exact-three executor. Requires actualUART500000ppm before RUN,
old250000/1000000 rejected; no automatic gain selection/retry or extra runs.

## Build and focused verification

A build PASS,219860B BIN; staticRAM130784/131008B,224B remaining. No stack/heap
shrink. Existing unused-function/RWX warnings remain. ReviewB no work and
unchangedBIN7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366.
PhysicalB untouched.

BIN SHA2563508081b2835eb4668aba861cfdc3abc3061948c37bd01be405d42e8eb74e474;
ELF SHA256f8400b14bc1d009c11ca78cc027615533241de6e845ae7b9e3b9e821a4ccec2c.
Freeze this build after stage for readback/capture provenance.

Two focused halfgain tests PASS at-Os/-O2 with-Wall/-Wextra/-Werror: signed
20mAestimate ->10mAcompensation, cap/slew/gap/fade/reentry/STOP/dynamiclowercap/
totalAW remain. Preprocessed FOC/current/angle/guard/power/readiness/task/speed
bodies identical to1.0; only helper scalar differs. Old1.0native tests PASS.
Three new harness tests PASS: files-only exactnewimage and actualB1095, fresh
physical gates and wronggain blocks beforeRUN, mocked exactly3ON points with
.5metadata and stop-on-independent-protection, no retries. Mocks/native tests
are not physical performance evidence.

Final related regression158/158PASS across36separately run modules;
`tmp/dob-feedback-gainhalf-regressions.log`. Includes previous gain1/default
feedback profiles, DOB filtering/model/admission/provenance, current/encoder/
readiness/outer completion, PWMpipeline and total-output antiwindup. No
historical firmware build directory was rebuilt by these tests.

## Manual procedure

Fresh confirmation received12V OFF, MCU powered, motorunlocked/unloaded/fixed/
guarded, wiring unchanged,12V/.5Alimit, operator present for3runs/immediatecut.
KeepOFF while inactiveA stage/two full readbacks preserveB/boot/config.
Separate powered/no-alarm/whole-three operator confirmation is required.
Original calibration/output-off/timing/stack/readiness preflight before each
600rpm run, same5sdrive/deceleration/12slease, trip1000rpm/travel30000deg.
Any independent protection, failed admission or off/halt evidence stops batch;
no automatic retries. Save full stoppedFlash/RAM and metrics after each point.
Ask physical12V OFF before restoringB selection; do not runB.

Compare three-run mean/sampleSD to priorOFF5/.25ON5/1.0ON3 as historical
noncontemporaneous cohorts, NOT randomizedsame-session A/B or loadstep response.
Primary acceleration/cruise MAE/overshoot/Iq/integrator; no automatic adoption
or stableB promotion from unloaded results.

## Gain0.5 A staged, not activated

Fresh physicalOFF confirmation received. Stage
`tmp/mechanical-ident-stage-1792738936814882700.json` PASS: inactiveA written,
two independent complete readbacks, originalB/boot/private/metadata unchanged,
activationfalse,motor_commands0,SD/MOE/PWMOFF and CPUhalted. Separate fresh
powered/no-alarm/whole-three-run confirmation required before activation.

## Three gain0.5 ON trials completed

After separate powered/no-alarm/operator confirmation, batch
`tmp/mechanical-ident-batch-1792739031739338900.json` PASS: exactly3/3 runs,
600rpm, actual UART GAIN_PPM=500000 in every run, no retries. Each run passed
calibration/output-off/timing/stack/readiness checks before its one RUN.
Stopped full Flash/RAM and observer/adapter/controller evidence were saved.

|Run receipt `mechanical-ident-run-...json`|Acceleration MAE rpm|Cruise MAE rpm|Overshoot rpm|Applied DOB peak mA|
|---|---:|---:|---:|---:|
|1792739031846768300|8.46130|3.28540|6.53192|5.72146|
|1792739075765127400|7.94553|2.47123|5.60706|9.63087|
|1792739106238555400|7.49172|3.49196|5.88104|7.86106|

## Mean +/- sample SD; historical comparison only

|Metric|Earlier OFF5|Earlier gain0.25 ON5|Current gain0.5 ON3|Earlier gain1.0 ON3|
|---|---:|---:|---:|---:|
|Acceleration MAE rpm|7.70189 +/- .91774|7.52873 +/- .88978|7.96618 +/- .48512|8.10686 +/- .69377|
|Cruise MAE rpm|2.25717 +/- .16145|2.25699 +/- .24240|3.08286 +/- .53967|4.20507 +/- .60461|
|Overshoot rpm|5.51954 +/- .40799|5.72614 +/- .52409|6.00667 +/- .47506|6.36633 +/- .34908|
|Iq command peak A|.416593 +/- .015507|.421877 +/- .013797|.428295 +/- .015461|.420440 +/- .003150|
|Integrator peak A|.124594 +/- .012203|.129827 +/- .009515|.131745 +/- .013652|.127498 +/- .006153|
|Applied DOB peak mA|0|4.86174 +/- .90492|7.73780 +/- 1.95762|14.98785 +/- 1.99236|

Current deceleration MAE6.64610 +/- .90119rpm; whole-observation DOB valid
fraction .786401 +/- .008402. Iq saturation seconds0, feedback clamp updates0
in all3. Largest command peak .444794A and applied DOB peak9.63087mA, below
unchanged .50A total/25mA compensation limits. No recorded current clipping
explains the tracking differences.

Gain0.5 has lower mean acceleration/cruise errors and overshoot than earlier
gain1.0, but higher than earlier gain0.25. There is no measured reason to
prefer0.5 over0.25 from this unloaded historical comparison. Cohorts were
not contemporaneous randomized paired A/B, have unequal sample counts and
run-to-run variation; these results do not isolate a causal gain effect or
prove load-disturbance rejection. No automatic gain selection or B promotion.

## Timing, closure and restored stable B

All3 have fault VALID=0, deadline miss0 and CCR late0. Worst FOC33.31176us,
minimum PWM commit margin15.12941us, minimum preflight task free stack2464B.
Adapter valid update counts6224/6263/6402, holds504/540/570, fades29/29/33;
these are update counts, not independent events or exact durations. Captured
applied compensation returned to0 after every run; outputs OFF and CPU halted.

User separately confirmed physical12V OFF after the batch. Restore receipt
`tmp/mechanical-ident-restore-1792739258244032100.json` PASS: original B,
boot/config/private unchanged, B application not run, motor_commands0,
metadata sequence1099 selects B, VTOR0x08040000, SD/BDTR/CCER0, CPU halted.
No further motor run. CandidateA remains staged; it was not promoted to B.
