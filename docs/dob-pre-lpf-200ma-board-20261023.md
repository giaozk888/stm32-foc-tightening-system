# One supervised600rpm DOB pre-LPF200mA board test

Fresh user confirmation received for12V OFF, MCU supplied, shaft unlocked,
motor unloaded/fixed/guarded, existing phase/current/SD wiring,12V/.5A supply,
operator available for immediate power cut. User authorized only inactiveA
update, keeping stableB. No DOB feedback or algorithm/limit change.

`tools/dob_pre_lpf_200_board.py` reuses reviewed V7 executor/decoder/safety
closure, proves actual prior V7/B1075 restore under its old100mA identity
BEFORE selecting new200mA hashes, validates compiled`.200f`, and requires
UART`JUMP_UA=200000` with other exact unused settings before the single motor
command. No extra point or automatic retry. Three new harness tests PASS:
files-only image/prior provenance, fresh physical OFF/ON gates, and100mA
configuration mismatch stops before RUN. No production firmware changed.

## Provenance and execution

- A BIN216620B SHA256
  `5bd9e2c52ffaeecf70d8c0b35f981b90e0bfa250aa3ae39620f2a5b411346301`.
- Stage:`tmp/mechanical-ident-stage-1792734395366395900.json` PASS.
  Two complete independent readbacks, B/boot/private/metadata unchanged,
  activationfalse, motor_commands0, CPU halted, outputs off.
- Separate fresh powered/no-alarm/operator confirmation received.
- Run:`tmp/mechanical-ident-run-1792734456546723200.json`.
- Batch:`tmp/mechanical-ident-batch-1792734456459132300.json` PASS safe
  acquisition/closure, not proof of mechanical identification or DOB accuracy.
- Whole stopped RAM SHA256
  `8b1fa2d24800f78941952d4f53f8408bf4ce1ed6d29149f507588219596cffb5`.
- Readonly UART confirms PREFILTER/TRUSTED,200000uA,3coherent points,
  filteredId60000uA/20000us, recoverable gap10000us, LATCH0/FEEDBACK0.
- +600rpm, Ka.000046875A/(rpm/s), same friction/BEMF, Iq±.5A,
  voltage1.6V, hardOC4A, trip1000rpm/travel30000deg and original lease/watchdogs.
  Boot-health/calibration/timing/stack/readiness passed before one motion run.

## Single-run historical comparison

|Metric|Prior V7 /100mA|New V7 /200mA|
|---|---:|---:|
|Whole-session observations|7870|7990|
|Valid DOB observations|4073|6260|
|Whole-session valid fraction|51.7535%|78.3479%|
|Selector inputs after motion qualification|7494|7463|
|Quarantined pairs|1536 /20.4964%|335 /4.4888%|
|Qualified recoveries (recovery frame invalid)|1230|319|
|Coherent new-level confirmations|39|5|
|Long-gap resets|0|0|
|Confirmed sustainedId events|0|0|
|Id pending duration peak|0us|0us|
|Valid disturbance mean, current-equivalent|-2.39885mA|-0.88325mA|
|Valid disturbance absolute peak|43.23383mA|18.06722mA|

These are TWO independent single trials, not repeated randomized A/B means.
Whole fraction includes startup/qualification/warmup/deceleration; no claimed
exact steady-state validity or longest continuous invalid interval. Reduced
exclusion follows a looser quality tolerance; smaller estimated disturbance
does NOT independently prove less actual disturbance or greater accuracy.

Six sparse UART snapshots near600rpm are valid1/status0 at approximately
587.89,600.73,602.50,596.55,597.79,600.26rpm (US11217179..13127128).
Previous near600rpm sparse snapshots were invalid. This supports improved
sampled availability only, NOT full continuous-valid coverage. Frame/ADC/stats
queries are sequential, not the same epoch. DOB remains shadow-only.

## Actual pre-LPF exclusion evidence

Trace trigger8677173us: preceding trusted Id12.243mA/Iq-9.520mA; suspect
Id-139.908mA/Iq378.179mA. Iq jump387.699mA exceeds200mA, so the WHOLE pair is
QUALITY_WAIT from first suspicion. Id LPF4.0578935 ->4.0578935mA, LPF_UPDATE0,
valid0, resetreason0. Next actual pair Id1.042mA/Iq-20.490mA returns to the
trusted level: QUALITY_RETURN, LPF3.7837508mA, recovery frame invalid with no
warmup credit/no reset, then ordinary good points resume. No stored suspect
replayed. This run did not reproduce a700mA captured event; that remains covered
by prior measured V7 and current offline+/-700mA tests.

All retained QUALITY_WAIT points keep LPF before/after exactly equal (including
two initial seed waits and later sampledIq jump).72-frame buffer complete,
16pre/24dense/32decimated tail.39dense pairs, maxLPF recurrence residual
1.1531e-9A, warmup error8.2433e-10s, holdLPFchange0, Id/reset/warmup violations0.
Retained actual reset event is WARMUP during motion qualification. Total155
reset calls include unretained history; no complete by-reason attribution.
Tail is decimated, not a complete20kHz waveform or all335rejected points.

Exports:`tmp/dob-pre-lpf-200-board-1792734456546723200.json` and `.csv`.

## Safety/timing and restored B

No motor protection fault; CUR_CONFIRM enter133/clear133/fault0,max2cycles102us.
FOC wallmax33.3117647us, deadline miss0, CCR late0, mincommitmargin15.1764706us.
Task stack preflight2548B free. DOB task max94us and tracecallback46us include
preemption; they are not FOC ISR runtimes. Legacy mechanical fit has0bins with
exclusive trace owner flag0x80000000: this is expected buffer reuse, NOT a
successful mechanical re-identification or a motor protection failure.

After STOP and ANALOG SAFE, fullFlash/RAM saved, SD/MOE/PWM off and CPU halted.
User separately confirmed12V OFF. Restore
`tmp/mechanical-ident-restore-1792734533319217000.json` PASS: original B227964B
CRC627317606 preserved with boot/private/config, metadata generation1079,
VTOR0x08040000, SD/BDTR/CCER0, CPU halted, motor_commands0, B application NOT run.
No additional motion or DOB current feedback enabled.
