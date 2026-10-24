# V5 skip-only DOB: one supervised600rpm test

Fresh physical OFF/setup and separate powered/no-alarm/operator confirmations
received. V5 inactive-A stage1792727170792261200 passed two full readbacks with
B/boot/config/private/metadata unchanged. One explicit +600rpm run, no retry.
Existing Ka=.000046875 A/(rpm/s),friction.105A,BEMFpsi=.00034866Wb,
Iq±.50A,voltage1.6V and all motor protections unchanged. DOB shadow only.

Run: `tmp/mechanical-ident-run-1792727241696824700.json`.
Batch: `tmp/mechanical-ident-batch-1792727241613499700.json`, PASS acquisition
and safe closure, NOT closed-loop DOB acceptance or calibrated torque accuracy.
RAM SHA1579226b2cadb09cf43cbc59a1a94931e71ad050482e5197b6b685f68c1e396d.
Raw trace exports: `tmp/dob-recoverable-board-1792727241696824700.json` / `.csv`.

## Whole-session results

-7880 actual ~1kHz task observations,2918 valid DOB observations:37.0305%.
 This denominator includes startup/qualification/warmup and deceleration/stop;
 it is not a steady600rpm valid fraction. V4 had0/7990, a different run, not a
 repeated controlled A/B mean. V5 no longer permanently locks after early spikes.
-7392 qualified selector inputs:5179 admitted (70.0622%),2213 raw-adjacent
 exclusions (29.9378%). Entire Id/Iq pair skipped if either jump>100mA.
-No blocked latch, no count/rate exit.982 gap recoveries,3 long-gap resets.
 Long gaps rewarm recoverably; no automatic motor restart or protection clear.
-The first retained valid trace frame is9120216us,520.978ms after arm8599238us;
 observer elapsed399.018ms. Decimated sampling brackets onset, not exact first
 valid sample time. Missing/recovery intervals earn no warmup credit.
-Mean valid positive disturbance=-.000580173 A equivalent, absolute peak
 .015745595 A. These are model residuals, not calibrated N*m or proof of loaded
 disturbance rejection. No DOB current feedback was applied.

## Actual skip/freeze/recovery proof

Trigger8604238us. Dense same-epoch trace:

|Relative ms|Raw Id mA|Decision|LPF absId mA|Warmup ms|Reset|
|---:|---:|---|---:|---:|---|
|-1.000|10.881|NORMAL|23.792|4.000|No|
|0.000|-106.359|DIRECT_REJECT|23.792|4.000|No|
|1.000|6.143|DIRECT_REJECT|23.792|4.000|No|
|1.999|35.070|GAP_RECOVERY|25.263|4.000|No|
|3.000|.762|NORMAL|24.095|5.001|No|

Both the outlier and its raw-adjacent return are skipped; the next calm actual
pair updates filters over actual2.999ms accepted interval but remains invalid,
and ordinary good data resume warming. No point substitution/clipping, no
permanent count latch. This does not prove excluded physical current was noise.

Complete V5 trace96frames:16pre/32dense/48tail at>=16ms. Dense47pair LPF residual
max9.31e-10A, hold LPF change0, warmup increment error6.45e-10s, reset/warmup
contradictions0. Tail is decimated, not consecutive waveform; no20kHz ADC claim.

No motor protection fault. FOC wall max33.305882us,deadline miss0,CCR late0,
minimum commit margin15.129412us. Motor task stack preflight2520B free.
DOB Observe wall max89us and trace callback wall max46us are task-side maxima
including preemption, not FOC ISR duration.

Conclusion: requested skip-only / recoverable policy is demonstrated and yields
valid shadow DOB output. Raw exclusions remain substantial (~30%), with3 long
data gaps; do not claim a few isolated bad points, stable continuous availability,
or readiness for closed-loop disturbance compensation from this single test.

## Original B restored after fresh physical OFF confirmation

Restore `tmp/mechanical-ident-restore-1792727325095184200.json` PASS. Original
physical B227964B CRC627317606,boot/config/private preserved; generation1067,
B application not run,motor_commands0,VTOR0x08040000,SD/BDTR/CCER0,CPU halted.
No further motor run. Physical12V OFF, MCU supplied.
