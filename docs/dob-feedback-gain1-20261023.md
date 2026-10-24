# DOB feedback gain1.0 diagnostic A, three600rpm trials

User requested gain1 and three runs. Interpreted as DOB feedback gain, NOT Ka,
speed/currentPI, torque/current limit or observer bandwidth. StableB untouched.
First fresh confirmation received for12V OFF; keep power off until separate
powered/no-alarm/whole-three-run operator confirmation. Other setup unchanged
from prior unloaded/unlocked/fixed/guarded trials; verify again on power-up.

## Minimal candidate change

`MechanicalDobFeedbackGain1Candidate` inherits prior feedback candidate and
defines `DOB_FB_GAIN=1.0f`. Header allows compile-time override, preserving.25
default for old profiles. Readonly CFG reports compiled gain dynamically,
`GAIN_PPM=1000000`; old profiles still report250000 if compiled, and previous
hash-pinned.25 images are NOT rebuilt. No other controller change.

`iq_dob = gain * valid_d_hat`, slewed at.25A/s and capped at
`min(.025A,.05*iq_limit)`; totalIq still±.50A. Same5ms short hold,20ms fade-tozero,
2ms freshness,200mA pre-LPF quarantine,60mA/20ms Id gate, model/bandwidth,
conditional AW on PI+accelerationFF+friction+DOB TOTAL, voltage1.6V, hardOC4A,
600rpm target/trip1000rpm/travel30000deg and all original lease/IRQ/protections.
Runtime defaultsOFF; guardedON only with idle and outputsOFF. No automatic
parameter application or formalB update. Gain1 may reach compensation cap;
record actual peak/clamp counts rather than assume fourfold applied output.

Production edits: `dob_feedback_candidate.h`, `dob_feedback_binding.inc`,
A CMakeLists/Presets. New gain1 native/tests and
`tools/dob_feedback_gain1_board.py`/test. Prior.25 firmware and board wrappers
retain their frozen hashes; no change to FOC actual current feedback.

## Build and focused regression

A compile PASS, BIN219852B, staticRAM130784/131008B (224Bremaining), no stack/
heap shrink. Existing unused-function/RWX warning classes remain. Review B
reports no work and unchanged hash
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
Physical stableB not flashed/rebuilt.

A BIN SHA256`cfb4a3c6b26add1533b7d50aeadd9f83cbdbc2bf684351b195468186c592b131`;
ELF SHA256`17c5f384fea5f1c84115b1a1a96806f62185af7bf7117661fb1f5ba46b663b74`.
Freeze this build for hardware provenance after staging.

Two new focused tests PASS, native-Os/-O2 with-Wall/-Wextra/-Werror: signed
20mA estimates converge to+/-20mA compensation before cap, slew/hold/fade/
re-entry/defaultOFF/STOP/dynamic lowerIqcap/total-output AW preserved. Actual
preprocessed FOC/current/angle/guard/PWM/power/readiness/task/speed update bodies
identical to.25 candidate; only helper gain and readonly report differ. Existing
three feedback tests also PASS (exactOFF randomized comparisons and protocol
guards/extreme reply capacity), including default.25 compatibility.

Final related regression:153tests across34separately run modules, ALL PASS;
`tmp/dob-feedback-gain1-regressions.log`. Includes existing DOB profiles/
provenance, mechanicalDOB, pre-LPF isolation, current admission/protection,
encoder completion/admission, outer completion/readiness, PWMpipeline and
speedantiwindup. No historical firmware artifact was rebuilt by those tests.

Three new gain1 harness tests PASS: files-only new hashes and actual prior
gain.25/B1091 restore; fresh OFF/ON gates and oldgain250000 rejects before ON;
mocked exactlythreeON points, correct first-run boot handling, independent
protection stops batch without retry. Firmware effect/performance NOT inferred
from mocks or native tests. Related DOB/FOC/encoder/AW regressions run separately
by module to avoid historical wrapper import-state contamination.

## Supervised procedure and interpretation

Use actual `tmp/mechanical-ident-restore-1792737355188145200.json` under prior
gain.25 identity BEFORE installing gain1 identity. Fresh OFF stage inactiveA,
two complete independent readbacks, preserveB/boot/config, no activation/motion.
Separate powered/no-alarm/operator confirmation then original calibration,
output-off timing/stack/readiness preflight before each of three600rpm runs.
Each run boots defaultOFF and guardedON must report gain1000000 before RUN.
Record all points, actualcomp/clamps/gaps/Id/Iq/speed/PI/AW/timing and saved
Flash/RAM; quality/performance not fabricated. Any independent protection,
failed admission or closure evidence stops wholebatch, no automatic retry.
After all or early stop: outputoff/halt, ask physical12V OFF, restoreB only.

Three new gain1 runs will be compared to previous OFF5/.25ON5 as historical,
noncontemporaneous reference, NOT randomized same-session A/B or a load-step
test. Primary metrics acceleration/cruise MAE, overshoot/Iq/integrator, not
stable-confirmation delay alone. No automatic gain selection or B promotion.

## New gain1 image staged, not activated

With freshly confirmed12V OFF, stage
`tmp/mechanical-ident-stage-1792738053302138500.json` PASS: inactiveA written,
two full independent readbacks, originalB/boot/private/metadata unchanged,
activationfalse,motor_commands0,outputsOFF and CPUhalted. Separate fresh
powered/no-alarm/three-run operator confirmation required before activation.

## Three gain1 ON trials completed

Fresh powered/no-alarm/whole-three-run operator confirmation received. Batch
`tmp/mechanical-ident-batch-1792738180125302200.json` PASS,3/3acquired with the
same frozen gain1 image, no retry, no safety/parameter increase. Each run
passed original calibration/output-off/timing/stack/readiness and explicit
unusedOFF ->guardedON gain1000000 readback before its one RUN. FullFlash/RAM
and observer/adapter/PI/timing evidence saved before analysis.

|Run receipt `mechanical-ident-run-...json`|Acceleration MAE rpm|Cruise MAE rpm|Applied comp peak mA|Clamp updates|
|---|---:|---:|---:|---:|
|1792738180212408900|8.90537|3.58870|14.40509|0|
|1792738224507026600|7.65187|4.79719|13.35184|0|
|1792738255048214500|7.76334|4.22931|17.20661|0|

RAM SHA256 respectively2731643941cb9d7cd1e514be400d0ecb38d24691320097eb4ebea9de2212dd28,
1ec6873d8c507bbc9d2045130bec9100d368813538278c0469c3fc5778aa3f9d,
af1cee76139815dccd31b73e0e3765f2668507c99b9d3ab00bfd9a04dcf822c5.

## Mean +/- sample SD and historical reference

|Metric|Previous.25gain ON5|New1.0gain ON3|
|---|---:|---:|
|Acceleration MAE rpm|7.52873 +/- .88978|8.10686 +/- .69377|
|Deceleration MAE rpm|7.21477 +/- .73508|8.30780 +/- .31589|
|Cruise MAE rpm|2.25699 +/- .24240|4.20507 +/- .60461|
|Overshoot rpm|5.72614 +/- .52409|6.36633 +/- .34908|
|Iq commandpeak A|.421877 +/- .013797|.420440 +/- .003150|
|PIpeak A|.307502 +/- .013797|.306065 +/- .003150|
|Integralpeak A|.129827 +/- .009515|.127498 +/- .006153|
|Iq saturation seconds|0|0|
|Appliedcomp peak mA|4.86174 +/- .90492|14.98785 +/-1.99236|
|WholeDOB validfraction|.783658 +/- .021266|.785812 +/- .013427|

Newgain1 has worse mean acceleration(+7.68%),deceleration(+15.15%),cruise
(+86.31%) and overshoot(+11.18%) relative to the earlier.25ON5 reference.
Every newcruise value3.59..4.80rpm exceeds earlier.25range1.93..2.54rpm. No
compensation cap update and no totalIq saturation occurred, so the observed
worsening is not explained by a recorded current clamp. Gain/bandwidth/model
noise, sign/phase and hold/slew interactions require separate evidence; this
experiment does not isolate a root cause. These are noncontemporaneous cohorts
with unequal sample counts, not randomized same-session paired A/B. It provides
no reason to adopt gain1 or promote stableB. No gain is automatically selected.

## Safety, closure and original B restored

All3have firstfault0, no independent protection, deadline miss0/CCRlate0,
outputOFF/CPUhalt evidence. MaximumFOC33.64706us; minimumcommitmargin across
three14.1647us, taskpreflightfree2516B. Actual bounded feedback peak remains
under25mA, not inferred from modeflag. Adapter freshGOOD6178/6252/6381,
HOLDupdates520/523/514,FADEupdates30/32/33; these are samplecounts, not isolated
events or exact durations. Sparse UART cannot reconstruct full applied waveform.

After STOP/ANALOG SAFE/capture/halt, user separately confirmed physical12V OFF.
Restore`tmp/mechanical-ident-restore-1792738356256376500.json` PASS: stableB/
boot/config/private preserved, B application NOT run, motor_commands0,
outputsOFF/CPUhalted. No further run, no automatic return trial or B promotion.
