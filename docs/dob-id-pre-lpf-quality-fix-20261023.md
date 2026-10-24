# DOB-only Id pre-LPF quality repair (V7 candidate A)

## Root cause, established BEFORE implementing the repair

Existing V6 native tests explicitly required first/second raw jumps to be
admitted. `DobAdmit_Push` returned1/JUMP_PENDING while run<3. The monitor then
updated iq_lpf and abs_id_lpf before checking filtered Id60mA/20ms. Therefore
an isolated spike and its return could occupy runs2/3: spike admitted, lower
return rejected. Raising the later gate or changing PI cannot undo that LPF
contamination. The old behavior was intentional policy, not a race in LPF code.

Same-session historical V6 evidence was independently redecoded with its frozen
ELF: `tmp/mechanical-ident-run-1792730979256712900.json`, hash verified. Actual
Id-77.5125 ->45.1671 ->699.7818 ->30.7392mA; the699.8mA point was JUMP_PENDING/2.
abs_id_lpf19.953636 ->52.326411mA, below60mA, so no Id timer. The repair does not
alter or relabel that original failed-policy acquisition.

## Minimal repair and boundaries

Only new opt-in A `MechanicalDobPreLpfCandidate`, adding
`FOC_DOB_ID_PRE_LPF_QUALITY`. All old V1..V6 images/configurations retain their
original compiled behavior. Formal B untouched; no flashing/reset/motor run.

1. Existing finite/source/current flags/timestamps/sequence/saturation checks
   run first. No pre-arm raw point silently seeds the DOB filters.
2. After motion qualification, three coherent actual source-qualified pairs
   are required to seed. Subsequent >100mA dq deviations from the last trusted
   pair are quarantined from the FIRST suspicion. Both current LPFs are held
   so an Id/Iq-correlated measurement anomaly cannot contaminate either input.
   The trigger is not a count that lets two suspicious values pass.
3. Keep a separate trusted reference and a quarantined candidate cluster. A
   real return within100mA of the trusted pair can recover directly even if
   its delta from the previous RAW spike is large. Otherwise require3coherent
   actual pairs within100mA of the FIXED first candidate, restarting that
   cluster on disagreement. Admit only the CURRENT qualified point, never
   replay/substitute the earlier stored suspects. Persistent actual current
   level changes must not be thrown away forever against a stale baseline.
4. A rejected point changes diagnostic raw history/quarantine storage only,
   not either LPF, accepted reference/timestamp, Id bad-duration/baseline,
   observer state/warmup, admitted count or valid statistics. Its published
   DOB frame is invalid with zero disturbance. No motor command is issued.
5. Short recoverable gaps<=10ms keep observer/warmup. The actual recovery
   pair uses the elapsed accepted-pair interval for a bounded endpoint
   filter/model update; that frame is invalid and earns no warmup credit.
   This is not reconstruction of the unknown waveform. Qualified recovery
   explicitly breaks Id-duration continuity; rejected data cannot advance,
   erase or move that timer. Ordinary good points then resume validity.
6. No trusted data for>10ms: one recoverable observer reset, invalid output;
   later coherent data reseed and complete original5/g (~398ms) warmup. No
   count/rate session latch or repeated reset on every rejected frame/reseed.
7. Existing filtered absId60mA/20ms confirmation remains after actual qualified
   LPF updates. A sustained coherent large Id is not reclassified as a forever
   isolated glitch: it can become a qualified real level, and the existing
   model-domain gate identifies sustained Id with one reset, not repeated
   resets. Continuous incoherent outliers instead cause the10ms data-gap path.

No independent verified raw-Id physical bound narrow enough to call699.8mA
impossible was available. ADC conversion constants are3300mV/4095counts/
120mV-per-A; these do not make.7A physically impossible. Iq command±.50A and
filtered Id60mA are NOT raw physical range limits. No such absolute limit was
invented, no clipping was added, and no FOC feedback/phase/angle/current PI/
speed PI/FF/PWM/IRQ/CUR_CONFIRM/CURRENT_INVALID/hard-overcurrent threshold was
changed. This repair detects suspicious jumps; it does not prove ADC noise or
physical current cause or guarantee all multi-point interference is rejected.

## Logs and exact formats

Same-epoch task trace V7 retains raw Id/Iq, signed raw-adjacent Id delta, quality
reason bits (seed/Id jump/Iq jump/wait/source/gap/return/level/first), LPF BEFORE
and AFTER, actual reset-hook reason, validity/initialized/warmup, Id timer and
confirmation state, pending/coherence count/filter-updated flags, ADC seq/
source/publication timestamps and speed. ISR still has no printf/new selection.

Reuse existing4608B buffer:64Bframe,16pre/24dense/32tail>=16ms. Header96B and
monitor856B unchanged. Admission204B (V6 160B). No heap/task-stack shrinking.
Tail is decimated, not all20kHz conversions. Readonly ADMIT CFG reports
MODE=PREFILTER/CONFIRM3/REFTRUSTED; ADMIT QUALITY reports quarantine state and
recoveries; replies remain within192B. No setters or DOB current feedback.

Decoder supports V1..V7, rejects LPF changes when LPF_UPDATE=0, Id timer change
on a rejected dense sample, reset reason/flag contradictions and fake validity.

## Production-C offline results

Linked actual monitor/admission/trace code at BOTH -Os and -O2 with
-Wall/-Wextra/-Werror. Seven focused unittest methods PASS, including old
hardware evidence re-decode, binary trace integrity/corruption checks, readonly
protocol capacity and preprocessed controller/protection equivalence.

|Synthetic regression|Actual result|
|---|---|
|Single+700mA, then normal|LPF20.000000mA before/during/after, no hard reset; actual return frame invalid, following normal frame valid|
|Full reproduced Id/Iq sequence|699.8mA quarantined, never replayed; no hard reset|
|Full reproduced Id path in monitor|LPF22.738095mA held throughout suspicious points, then falls on qualified5.8mA return|
|Rejected sample during pending Id timer|5000us and high-baseline flag unchanged until qualified recovery breaks continuity|
|Sustained coherent+700mA|First2quarantined, latest3rd qualifies real level; existing20ms Id condition resets ONCE; later normal data rewarm/recover|
|Sustained incoherent±700mA|Invalid output, one10ms gap reset, no session latch; later normal data rewarm/recover|
|Startup single+700mA|Not allowed to seed; three later coherent normal pairs establish initial LPF|
|Iq-correlated outlier|Neither DOB current LPF updated|
|100mA equality/nonfinite/source failure/real FAULT|Boundary/source logic preserved; actual fault stays frozen, no auto restart|

Native actual log:`tmp/dob-id-pre-lpf-native-results.log`. No synthetic result
is presented as new board evidence or a measured improvement in DOB accuracy.

## Build and modified files

A Flash216620B,staticRAM130704/131008B (304B left); compiler/linker PASS.
BIN SHA018cdb371c9a3262af9998c766e4a66b13e0d1c95070f8d5a88ea72ed9de0809,
ELF SHA7604165bb3f912727fee92acf5e51ce099e923ebe20387ea5b4f46988e93d0dc.
B review build PASS, unchanged SHA7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366.
Frozen V6 BIN unchanged c6b35a3e8a420c7de811c72abdb09568f67b424602582dc9f94c940e8d7724a5.
Main warning classes equal V6; historical unused-function/RWX warnings remain.

New: firmware_common/dob_id_pre_lpf_quality.h,tests/dob_id_pre_lpf_host.c,
tests/test_dob_id_pre_lpf.py,this report. Modified: DOB admission/monitor/trace/
readonly binding, A CMakeLists/Presets, tools/dob_id_trace_report.py. Main FOC,
motor-control and independent safety functions unchanged in preprocessing.

Related regression log:`tmp/dob-id-pre-lpf-regressions.log` (result recorded
after completion below). No board operation this turn; original B1071 remains
restored from1792731081701396300,12V last confirmed OFF,outputsOFF,CPUhalted.

Final related regression175/175 PASS (including7 new methods). Candidate A and
B review hashes above rechecked after testing. No new hardware data, no
automatic observer feedback or changes to any other algorithm parameter.
