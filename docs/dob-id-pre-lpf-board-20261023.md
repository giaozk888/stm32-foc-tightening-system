# V7 pre-LPF quality: one supervised600rpm retry

User requested one retry using the pre-LPF repair, not the old V6 first2pass
policy. DOB remains shadow-only; no Iq feedback, parameter/threshold changes,
automatic retry or extra point. Existing600rpm/Ka=.000046875/Iq±.50A/voltage1.6V
and motor safety architecture remain.

New `tools/dob_id_pre_lpf_board.py` pins reviewed V7 BIN/ELF/SIZE, trace ABI7,
admission ABI204B and MODE=PREFILTER/REFTRUSTED/CONFIRM3/ID_US20000. It proves
the actual prior V6/B1071 restore1792731081701396300 before installing new
identity. Existing stage/boot/calibration/timing/stack/readiness/one RUN/safe
capture/Brestore workflow remains. Four new harness tests PASS, including
files-only provenance, OFF/ON gates, exact unused config/readbacks, corrupt
state counters; prior175related regressions passed with unchanged firmware.

Fresh physical OFF/setup confirmation received: MCU supplied, shaft unlocked,
unloaded motor fixed/guarded, U/V/W and IU/IV/SD wiring unchanged,12V/limit.5A,
operator available for immediate power cut. Stage
`tmp/mechanical-ident-stage-1792732847702111200.json` PASS: inactiveA written,
two full independent readbacks,B/boot/private/config/metadata unchanged,
activation=false,motor_commands0,SD/BDTR/CCER0,CPUhalted. Metadata remains1071.
Separate powered/no-alarm/operator confirmation is still required; no motion.

## One V7 run completed and actual quarantine verified

Fresh powered/no-alarm/operator confirmation received. One +600rpm test only,
no retry, no DOB feedback. Run
`tmp/mechanical-ident-run-1792733225686577700.json`, batch
`tmp/mechanical-ident-batch-1792733225603127700.json`, PASS safe acquisition and
closure. RAM SHA8a47a8497149060d845772242b1d831291d585214b6f9226e1486f856ddd2b20.
Exports:`tmp/dob-id-pre-lpf-board-1792733225686577700.json` / `.csv`.

### Real measured ~-699mA point did NOT enter the LPF

Trigger8546282us. This is a new negative measured excursion, not a claim that
the original positive699.8mA event was physically reproduced unchanged.

|Relative ms|Id mA|Iq mA|Raw adjacent Id delta mA|Decision|LPF before/after mA|Warmup ms|Reset reason|
|---:|---:|---:|---:|---|---|---:|---|
|-1.023|12.780|152.011|-.352|NORMAL|13.258/13.235|24.997|None|
|0.000|-698.887|-771.630|-711.666|QUALITY_WAIT|13.235/13.235|24.997|None|
|1.011|-36.976|108.079|661.911|QUALITY_RETURN|13.235/15.427|24.997|None|
|2.011|21.837|212.231|58.812|QUALITY_WAIT (Iq jump)|15.427/15.427|24.997|None|
|3.011|-3.347|175.601|-25.184|QUALITY_RETURN|15.427/14.329|24.997|None|
|4.025|-15.288|172.021|-11.941|NORMAL|14.329/14.375|26.011|None|

The large measured Id AND Iq pair was quarantined from its first occurrence.
Actual finite/source-qualified raw return was accepted against the trusted
baseline, despite its large raw-adjacent delta; no suspect replay. This event
left LPF, Id timer and warmup unchanged, with no hard observer reset. Recovery
frame remains invalid/no warmup credit; ordinary good samples resume warming.
The recorded raw value is not proof of ADC noise versus actual current cause.

All4 retained quarantined frames (3dense,1decimated) have exactly equal LPF
before/after, LPF_UPDATE0,invalid output,reset_reason0. Dense rejects also retain
the preceding warmup and Id timer unchanged. Read-only file assertions PASS.
This directly verifies sampled events, not a stored trace of all1536 rejects.
Dense39pair maxLPF residual4.78e-10A,heldLPFchange0,warmup increment error4.04e-10s,
reset/warmup contradictions0. Full72-frame V7 buffer complete,tail decimated.

### Whole-session availability and limitations

-7870 actual ~1kHz observations,4073valid:51.7535% overall.
-7494selector inputs after motion qualification,5958admitted,1536quarantined
  (20.4964%).1230recoveries,39coherent new-level confirmations,1initial seed.
-No count/rate latch,no long-gap>10ms reset,no confirmed Id event; Id pending
  duration peak0us (this does not prove raw Id was always small).
-Mean valid positive disturbance=-.002398849A equivalent,abs peak.043233830A.
  Not calibrated N*m, loaded-disturbance accuracy or closed-loop effect.
-Previous V6 independent single run had76.05% validity, versus51.75% now.
  V7 does not get high availability by allowing two suspects into the LPF;
  lower availability is not hidden or tuned away. These are separate single
  trials with startup differences, not controlled repeated A/B averages.

Retained trace contains24 actual reset frames, all reason4 ZERO_SPEED: measured
speed fell below the existing20rpm model-domain minimum. First captured case
at+8.024ms is18.664rpm, then several~2..16rpm observations. These are NOT Id,
quarantine or motor protection faults. Warmup cannot accumulate there. The
retained~.56s trace contains no valid frame, but full-session4073valid points
occur later; do not report zero availability from this limited window. Do not
extrapolate sampled24resets into a full-session per-reason count. No speed,
model-min-speed or other parameter was changed to bypass this behavior.

### Safety, timing and original B restored

No motor protection fault. FOC wall max33.311765us,deadline miss0,CCR late0,
minimum commit margin14.847059us. Motor task preflight free stack2548B.
DOB monitor wall max94us / trace callback46us are task-side maxima including
preemption, not FOC ISR compute duration. Full stopped Flash/RAM saved.

User affirmed physical12V OFF in response to shutdown request. Restore
`tmp/mechanical-ident-restore-1792733313738259200.json` PASS: original physical
B227964B CRC627317606,boot/config/private preserved; metadata generation1075,
B application not run,motor_commands0,VTOR0x08040000,SD/BDTR/CCER0,CPUhalted.
No further motor run or automatic observer feedback.
