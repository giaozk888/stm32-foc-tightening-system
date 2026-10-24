# V6 persistent-quality DOB: supervised +600rpm verification

User requests one test of the confirmed candidate policy: adjacent raw dq jump
>100mA for3consecutive points before exclusion (first2admitted); filtered
absId>60mA for20ms continuous admitted time before model unavailability. No
controller/phase/angle/protection changes, no DOB feedback to Iq, no retry.

New `tools/dob_persistent_board.py` pins V6 ELF/BIN/SIZE and ABI160B, trace6,
MODE=PERSIST/POINTS3/ID_US20000/REFRAW/LATCH0 and unused persistent counters.
It first proves actual V5/B1067 restore1792727325095184200, then uses existing
inactive-A stage / separate powered confirmation / calibration / original
timing and stack / readiness / one +600rpm / safe full capture / OFF-B restore.
Four new native-free harness tests PASS: exact files-only provenance, fresh
power gates, whitelist and unused readbacks, corrupt admission counters.
Candidate code unchanged since164related regressions passed.

Fresh user confirmation:12V OFF,MCU supplied,shaft unlocked/unloaded motor
fixed/guarded,wiring unchanged,12V supply limit.5A,operator available for power
cut. Stage `tmp/mechanical-ident-stage-1792730899420669600.json` PASS: V6 A
written,two full independent readbacks,B/boot/private/metadata unchanged,
generation1067,activation=false,motor_commands0,outputsOFF,CPUhalted.
Separate ON/no-alarm/operator confirmation required before any activation.

## One run completed

Fresh ON/no-alarm/operator confirmation received. One run only, no retry:
`tmp/mechanical-ident-run-1792730979256712900.json`, batch
`tmp/mechanical-ident-batch-1792730979182703400.json`, PASS safe acquisition and
closure. This is not a validation of closed-loop disturbance rejection.
RAM SHA7d64999cde1a578e0a67ea8c1b716223bcdd3af851ebc1cd12570b4e925196cb.
Exports `tmp/dob-persistent-board-1792730979256712900.json` and `.csv`.

### Availability and exclusion accounting

|Metric|V5 previous independent run|V6 this run|
|---|---:|---:|
|Total actual task observations|7880|8000|
|Valid DOB observations|2918|6084|
|Whole-session valid fraction|37.0305%|76.0500%|
|Armed-selector inputs|7392|7488|
|Admitted actual pairs|5179|6905|
|Excluded actual pairs|2213|583|
|Excluded / armed inputs|29.9378%|7.7858%|
|Count/rate session latches|0|0|
|Long-gap observer resets|3|0|

These are two separate single trials, not repeated A/B averages. Whole-session
denominators include startup/qualification/warmup/deceleration/stop, not a
steady600rpm valid rate. Increased availability alone does not prove accuracy.

V6 had2271 above100mA raw-adjacent suspect points (30.3285% of selector inputs):
1688 first/second pending points were deliberately admitted,583 points at
run>=3 excluded. Thus raw jumps did NOT disappear; the policy admits more.
277 gap recoveries, maximum jump run11, no permanent latch. No retroactive
deletion, substitution or fake-valid missing sample. Filtered Id pending
continuous duration peak8000us,0 confirmed20ms entries/Id recoveries. Short
high-Id episodes did not reset the observer. No real20ms Id event occurred, so
its exact boundary/recovery is offline-tested, not newly demonstrated in hardware.

First retained valid trace frame at9050177us,416.002ms after arm8634175us;
observer warmup406.002ms. Decimated tail does not identify exact first-valid
time. Mean valid positive disturbance=-.000348028 A equivalent, absolute peak
.018668981 A; no calibrated N*m, loaded accuracy or feedback effect claim.

### Same-epoch3-point behavior, including the tradeoff

Trace trigger8636173us; dense actual records:

|Relative ms|Decision/run|Raw Id mA|Raw Iq mA|LPF absId mA|Warmup ms|Reset|
|---:|---|---:|---:|---:|---:|---|
|0.000|JUMP_PENDING/1|45.167|52.060|19.954|1.998|No|
|1.000|JUMP_PENDING/2|699.782|-215.617|52.326|2.998|No|
|2.001|RUN_REJECT/3|30.739|62.655|52.326|2.998|No|
|3.000|GAP_RECOVERY/0|23.543|75.095|49.710|2.998|No|
|4.000|NORMAL/0|5.828|94.156|47.620|3.998|No|

This is the requested first2admit/thirdexclude policy, but also its limitation:
the large699.8mA Id point was admitted and its lower return excluded, because
the latter was the third consecutive raw jump. The large measured point is
not proved to be ADC noise or real motor current. Do NOT describe this policy
as removing every spike. No firmware change or extra test was made to conceal it.

Full96-frame V6 trace complete; dense47pair LPF residual max3.19e-9A,
held LPF change0, warmup increment error8.55e-10s, reset/warmup contradictions0.
Only recorded reset in retained window is initial qualified arming; tail16ms
decimated, not a full20kHz waveform or complete history of all resets.

The files-only decoder's descriptive note was corrected after capture to
distinguish the existing20ms LPF from the NEW separate20ms confirmation time;
firmware/BIN/ELF unchanged. Exports use corrected description.7 related native/
decode tests re-ran PASS, `tmp/dob-persistent-postboard-report-tests.log`.

### Safety, timing and restore

No motor protection fault. FOC wall max33.252941us,deadline miss0,CCR late0,
minimum actual commit margin15.170588us. CUR_CONFIRM140entered/140cleared/0fault.
Motor task preflight free stack2536B. DOB Observe wall max94us, trace callback
wall max45us include task preemption and are NOT FOC ISR execution times.

After fresh user physical12V OFF confirmation, restore
`tmp/mechanical-ident-restore-1792731081701396300.json` PASS: original physical
B/boot/config/private preserved, B not run,motor_commands0,SD/BDTR/CCER0,
CPUhalted at originalB selection. No further motor run.
