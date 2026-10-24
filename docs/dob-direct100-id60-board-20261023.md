# V4 direct100mA/Id60mA: one supervised +600rpm board test

User confirmed physical12V OFF, MCU supplied, shaft unlocked/unloaded motor
fixed/guarded, U/V/W and IU/IV/SD wiring unchanged,12V supply current limit0.5A,
operator present for immediate power cut. Update inactive A only, preserve B.

`tools/dob_direct100_board.py` pins reviewed V4 image/ELF identity,112B admission
and V4 trace ABIs, MODE=DIRECT, jump100mA, filtered-abs-Id60mA, accepted reference,
unchanged gap/exit bounds and unused50ms start guard. Actual prior B1059 restore
`tmp/mechanical-ident-restore-1792725093959340300.json` is proved before installing
new image identity. Existing boot/calibration/timing/stack/readiness, one600rpm
RUN, shutdown/capture and B restore gates remain. No feedback or automatic retry.
Four new harness tests plus six current-profile tests PASS immediately pre-stage.

Fresh separate ON/no-alarm confirmation is required after inactive A staging.
No threshold/controller adjustment or extra run is implied by poor quality.

Inactive-A stage `tmp/mechanical-ident-stage-1792725901627628500.json` PASS:
two full independent readbacks, B/boot/private/metadata preserved;
activation=false,motor_commands=0,SD/BDTR/CCER=0,CPU halted. Fresh ON/no-alarm
confirmation requested separately. No motion yet.

## One run completed: direct exclusion works, overall DOB quality NOT accepted

Fresh ON/no-alarm confirmation received. Batch
`tmp/mechanical-ident-batch-1792725957883388600.json` PASS means safe acquisition
and closure, NOT successful DOB qualification. Run:
`tmp/mechanical-ident-run-1792725957959011200.json`.
RAM SHA256 `ec7ec592442e5c8532663160d85651ad318fe65ae4aad9d58b5db96947923388`.
Exact reviewed image and runtime config confirmed DIRECT100000uA,
ID_MAX60000uA, REF=ACCEPTED, unchanged GAP2500us/CONSEC2/window32/maxhold4.

### Admission results

-7990 total observations,377 pre-arm observations,qualifier50035us,
  armed at8469223us using the original minimum-speed requirement.
-7614 armed-admission inputs,31 accepted pairs,4 direct threshold exclusions,
 0 pending/confirmed-isolated/persistent-transition/unresolved classifications.
-Fourth excluded pair triggers the unchanged second-consecutive-hold exit:
 BLOCKED at8503218us,33.995ms after arming. One latched diagnostic exit, no retry.
-DOB valid0/7990; rejected quality observations7583. This result is NOT usable
  DOB. A lower frozen LPF or removing legacy transition labels is not sufficient.

### Actual same-epoch proof: individual exclusions do not reset

Relative zero is the first direct exclusion, timestamp8482217us,seq167283.
V4 complete96-frame window includes arming, first exclusions, recovery AND actual
later latch (unlike V2/V3 windows). No timestamp encoding error.

|Relative ms|Raw Id mA|Raw Iq mA|Decision|LPF abs Id mA|Warmup ms|Reset|
|---:|---:|---:|---|---:|---:|---|
|-0.998|-2.665|66.200|NORMAL|36.388|11.996|No|
|0|60.633|261.343|DIRECT_REJECT|36.388|11.996|No|
|1.006|-6.641|19.412|GAP_RECOVERY|33.679|11.996|No|
|2.000|-3.122|43.062|NORMAL|32.232|12.990|No|
|18.001|64.424|279.909|DIRECT_REJECT|23.360|27.991|No|
|19.001|-50.119|124.609|GAP_RECOVERY|25.793|27.991|No|
|20.001|17.647|235.945|DIRECT_REJECT|25.793|27.991|No|
|21.001|46.028|276.645|BLOCKED: consecutive2|25.793|0|Yes|

The first raw pair was immediately excluded at its own call, no future return
wait, no filter/reference update and no warmup reset. Recovery uses the actual
pair/time gap but remains invalid and earns no warmup credit. This mechanism
behaved as requested; it does not prove any discarded raw current is ADC noise.

The final latch is NOT the filtered-Id60mA gate: actual LPF25.793mA remained well
below it. It is also NOT hard overcurrent, encoder or motor timing protection.
It is the separately retained consecutive-rejection bound for DOB quality.

### Reference distinction matters

Last accepted reference at+19.001ms is Id-50.119mA/Iq124.609mA.
At+20.001ms the accepted-reference Iq jump is111.337mA, so the pair is excluded.
At+21.001ms the accepted-reference Iq jump is152.036mA, so it is excluded again
and the existing consecutive2 boundary latches.

But between the two latest RAW pairs (+20.001→+21.001), Iq changes only40.699mA
(Id changes28.381mA), below100mA. Therefore do NOT claim both raw-adjacent jumps
exceeded100mA. The implemented and explicitly stated reference is the last
ACCEPTED pair, not previous raw. This protects reference contamination from an
excluded spike but can reject a genuine persistent current-level change. It is
the concrete limitation revealed here. Do not silently change reference, erase
the exit bound or promote an excluded level based on this one test.

### Verification and safety

Dense47-pair checks: maximum LPF recurrence residual1.85e-9A, held LPF change0,
reset/warmup contradictions0, warmup increment error7.37e-10s. Largest retained
LPF57.658mA occurs at arming below60mA. Source seq/publication time and raw dq
values are recorded, not all20kHz ADC conversions or analog aperture timing.

No first protection fault. FOC wall maximum33.258824us, deadline miss0,CCR late0,
minimum actual CCR margin15.182353us. MotorCtrl preflight free stack2548B.
No DOB feedback, parameter/threshold changes, automatic retry or extra run.
SD/MOE/CCER off, CPU halted, full Flash/RAM saved.

Exports: `tmp/dob-direct100-board-1792725957959011200.json` and `.csv`.
Verdict: requested per-point exclusion/no-reset verified; complete configuration
NOT accepted because retained consecutive2 policy latched before observer warmup.
No new mechanism selected or implemented as part of this verification.

## Original B restored

After user physical12V OFF confirmation,
`tmp/mechanical-ident-restore-1792726037058652600.json` PASS:
original B/boot/config/app-private regions preserved; B application not run,
motor_commands0,VTOR0x08040000,SD/BDTR/CCER0,CPU halted. No further motor run.
