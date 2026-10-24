# DOB OFF/ON five repetitions each, same frozen A

User explicitly requested five runs of each mode. Fixed schedule
OFF,ON,OFF,ON,OFF,ON,OFF,ON,OFF,ON;600rpm, same frozen219856B feedbackA
BIN9d4dae1bc55fb85fa5b821651ee0886e670644ad00ef3c77cd2923b3ce075aad,
ELFf1c61f2830ea1ca4046ef42d940a9e396737d0fd3cc9b63c92511bf1b0a6bc9a.
No firmware/gain/current/voltage/model/safety parameter change. DOBgain.25,
compensation<=min25mA,5%IqLimit; totalIq±.50A. Original600rpm S-curve,5sdrive,
deceleration/12slease and all protections preserved. No stableB modification.

`tools/dob_feedback_repeat5.py` reuses the reviewed single-point executor,
full calibration/power-off/timing/stack/readiness admission, exact unused
feedback/readbacks before RUN, STOP/ANALOGSAFE and full stoppedFlash/RAM/halt.
Each new run boots fresh and starts defaultOFF; ON is guarded explicitly only
for designated ON rounds while output is OFF. Original boot mailbox is written
only for the first round; subsequent rounds use full saved Flash comparison.
Every prior run must be acquired, have outputsOFF/CPUhalted and correct mode
before next run. Any independent protection, failed admission, transport or
off/halt evidence failure stops the ENTIRE batch; never retries/repeats a
failed point or increases gain. No deliberate external load is applied.

Summary uses each current-run persisted speed/FF/friction/feedback statistics,
with mean/sampleSD/min/max for OFF5 and ON5 plus chronological paired
ON-minus-OFF differences. Acceleration/cruise speed MAE are primary metrics,
not stable-motion confirmation delay. Only measured/proven values reported;
missing phase durations yield missing metric, not fabricated zero error.
Unloaded speed tracking is not calibrated torque or loaded-disturbance rejection.

Four new harness tests PASS: files-only exact image and actual prior B1087
restore; fresh physical OFF/ON gates before setup; mocked all10 immutable modes
with actual halt/closure flags and no next-point on independent fault or unsafe
closure; actual previous one-pair metric/unit/ordering verification. No hardware
in tests. Firmware/B not rebuilt for this repeat request.

Fresh user confirmation received:12V OFF, MCU powered, unlocked/unloaded motor
fixed/guarded, wiring unchanged,12V/.5A limit, operator present throughout all10
runs with immediate power cut available. Baseline restore is actual
`tmp/mechanical-ident-restore-1792736567554269700.json` under its original
feedback image/B1087 identity; no old receipt reinterpreted under new firmware.
Separate fresh powered/no-alarm/operator confirmation required before any RUN.

## Actual ten-run acquisition completed

Stage`tmp/mechanical-ident-stage-1792736892737660200.json` PASS: sameA, NO
flash programming; two complete independent readbacks, B/boot/private/metadata
unchanged, activationfalse,motor_commands0,CPUhalted/outputsOFF. Fresh powered/
no-alarm/whole-batch operator confirmation received. Batch
`tmp/mechanical-ident-batch-1792736958033120400.json` PASS,10/10runs acquired,
OFF/ON alternate exactly5each, no automatic retry/gain change. Parent receipt
retains each run/Flash/RAM path/hash, full aggregate mean/sampleSD/min/max and
all five chronological ON-minus-OFF pairs. No run was dropped for bad tracking.

|Run|Mode|Receipt `mechanical-ident-run-...json`|Acceleration MAE rpm|Cruise MAE rpm|
|---:|---|---|---:|---:|
|1|OFF|1792736958116358500|6.51430|2.03189|
|2|ON|1792737002202102300|7.07508|2.54355|
|3|OFF|1792737032544944900|8.43558|2.27390|
|4|ON|1792737062776546600|7.95683|2.38634|
|5|OFF|1792737093066918200|8.72493|2.40973|
|6|ON|1792737123266722900|6.84053|2.32836|
|7|OFF|1792737153555552300|7.09195|2.16603|
|8|ON|1792737183871692700|8.89787|1.93468|
|9|OFF|1792737214211694000|7.74271|2.40430|
|10|ON|1792737244823862500|6.87332|2.09203|

## Mean +/- sample SD across five runs per mode

|Metric|OFF|ON|
|---|---:|---:|
|Acceleration MAE rpm|7.70189 +/- .91774|7.52873 +/- .88978|
|Deceleration MAE rpm|7.10134 +/- .88487|7.21477 +/- .73508|
|Cruise MAE rpm|2.25717 +/- .16145|2.25699 +/- .24240|
|Low-speed MAE rpm|12.46129 +/- .31872|12.51685 +/- .27902|
|Overshoot rpm|5.51954 +/- .40799|5.72614 +/- .52409|
|Maximum instantaneous speederror rpm|72.82255 +/-10.36802|68.58171 +/-10.06256|
|Iq commandpeak A|.416593 +/- .015507|.421877 +/- .013797|
|SpeedPI peak A|.302218 +/- .015507|.307502 +/- .013797|
|Speed integralpeak A|.124594 +/- .012203|.129827 +/- .009515|
|Iq saturation seconds|0|0|
|Existing stable-motion confirmation delay ms|347.624 +/-69.020|380.210 +/-63.862|
|Whole-session DOB validfraction|.789233 +/- .006048|.783658 +/- .021266|
|Applied compensation peak mA|0|4.86174 +/- .90492|
|FOC wallmax us|33.26118 +/- .02105|33.36353 +/- .14175|

ON acceleration MAE mean is2.2484% lower, but0.17317rpm difference is small
relative to roughly.9rpm between-run SD. Paired acceleration differences
(ON-OFF):+.56078,-.47875,-1.88441,+1.80593,-.86939rpm, mixed directions.
Cruise MAE essentially identical (-.0078%); paired differences also mixed.
ON overshoot mean+3.7429%,Iqcommandpeak+1.2684%,integralpeak+4.2007%.
The previous single-pair acceleration worsening was not stable across these
repeats; neither is a clear repeatable improvement now established. This
descriptive five-pair unloaded experiment is not a formal significance/causal
claim. Stable-motion delay is not the main DOB benefit criterion and can differ
before observer warmup. No deliberate load-step was applied, so disturbance
rejection under a calibrated load remains untested. Do not promote to stableB
or increase gain automatically based on these results.

## Feedback and safety closure

All OFF compensation peaks exactly0. All ON runs show actual nonzero bounded
feedback peaks4.12890,5.05051,4.16550,6.33304,4.63076mA, well under25mA cap;
not merely mode flags. All10preserve snapshot firstfault0, deadline miss0,
CCR late0, per-runoutputsOFF/CPUhalted. Maximum FOCwall across10=33.54706us.
Each reset boots fresh with defaultOFF; designatedON was confirmed by guarded
command/config/model/direction/runtime and savedRAM, not persistently written.

After last run, STOP/ANALOG SAFE/fullFlash/RAM captured, SD/MOE/PWMOFF,
CPUhalted. User separately confirmed physical12V OFF. Final restore
`tmp/mechanical-ident-restore-1792737355188145200.json` PASS: stableB/boot/
config/private preserved, B application NOT run, motor_commands0, CPUhalted,
outputsOFF. No further motion or parameter/firmware change.
