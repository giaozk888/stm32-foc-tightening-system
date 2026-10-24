# V5 DOB: previous-raw exclusion, recoverable observation gaps

Only opt-in candidate A `MechanicalDobRecoverableCandidate`. Formal physical B,
controller/reference/actuator paths and independent protection are unchanged.
DOB remains shadow-only: no disturbance estimate is added to Iq.

User policy: skip an entire Id/Iq pair when either raw-adjacent jump >100mA;
do not update LPFs or warmup with that pair, do not count exclusions towards a
permanent session exit. A rejected finite/source-qualified RAW pair updates
only the next comparison baseline, never the current LPFs or mechanical model.
A spike and its return may therefore both be excluded; a subsequent calm pair
can recover. This does not prove any excluded actual current is ADC noise.

Short gaps <=10ms preserve observer state/warmup. Recovery updates the filters
and observer over the actual accepted-pair interval, a bounded endpoint
approximation, NOT reconstruction of missing current. Both skipped epochs and
the recovery epoch are invalid and earn no warmup credit. Ordinary good epochs
then resume validity. Existing shadow observer dt ceiling10ms defines this
model-only gap bound; no control/encoder watchdog is relaxed.

Once a gap exceeds10ms, reset the observer, invalidate output and stop retaining
old warmup. Do not integrate across the long hole. A subsequent qualified calm
pair reseeds LPFs/observer at elapsed0 and completes fresh5/g (~398ms) warmup.
No count/rate/BLOCKED latch, no motor auto-retry or protection fault clearing.
Original source/sequence/saturation checks, min-speed50ms qualification and
filtered abs(Id)<=60mA gate remain; those can independently invalidate DOB.

New RAM admission ABI124B; monitor856B and trace header96B unchanged. Trace V5
uses the existing4608B buffer:16 pre /32 dense /48 tail at>=16ms (tail covers
>398ms warmup). No claim of complete20kHz ADC waveform or dense tail replay.
Read-only ADMIT CFG reports MODE=SKIP,REF=RAW,LATCH=0,GAP_US=10000; ADMIT GAPS
reports stale/reset/recovery counters. Original V1..V4 decoders remain supported.

Offline fixtures at -Os/-O2:100mA boundary both axes/signs, unchanged LPF and
warmup on exclusions, actual V4 false-latch pair (40.699mA raw delta),50 sparse
outlier/return groups without latch,30 alternating exclusions -> one long-gap
reset -> fresh warmup -> valid again,60mA Id gate, source failure and real FAULT
no auto-restart. Actual retained continuous45-point/43.989ms window:5 exclusions,
40 admissions, no latch. It is shorter than warmup and not proof of useful DOB.

A build:215568B flash,130624/131008B static RAM (384B remaining), no stack/heap
reduction. BIN SHA2765b2c0da56ec99075764098357cd88b97e47f79334485665144f334d072803;
ELF SHA8a41096db0426b899b54fb87018e647d5e8a4a62385f8cc47a9751f1e05ce589.
B review build unchanged SHA7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366.
Main warning classes equal V4; existing unused-function / RWX warnings remain.

Board preparation uses `tools/dob_recoverable_board.py`, exact A/B1063 restore
provenance, fresh physical OFF before stage, two full readbacks with B/boot/
config/private preservation. Separate fresh powered/no-alarm/operator-present
confirmation before activation. One existing supervised+600rpm diagnostic,
Iq±.50A, voltage1.6V, drive5s+decel, existing closure/lease and protections.
Record safe stopped Flash/RAM before analysis, then request physical OFF and
restore original B without running B. Quality failure is not motor safety PASS.

Related regression153 PASS plus4 new board-harness tests PASS (157 total).
Fresh physical OFF/setup confirmation received. Stage
`tmp/mechanical-ident-stage-1792727170792261200.json` PASS: two independent full
readbacks, B/boot/private/metadata unchanged, activation=false,motor_commands=0,
SD/BDTR/CCER=0,CPU halted. Original metadata generation1063 unchanged. Separate
fresh ON/no-alarm/operator confirmation is still required; no motion yet.
