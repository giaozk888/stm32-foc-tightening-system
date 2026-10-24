# DOB-only pre-LPF 200mA candidate A

User requested changing the DOB jump threshold from100mA to200mA. No flashing,
activation, reset, motion or DOB current feedback is authorized/performed here.

## Scope and signed-current semantics

New opt-in preset `MechanicalDobPreLpf200Candidate` inherits the existing V7
pre-LPF quarantine policy. The only production behavior difference is the
compile definition `DOB_ADMIT_JUMP_A=.200f`. The historical100mA image and its
hash-pinned board harness remain unchanged; do not run the old board wrapper
expecting200mA. This new build is not installed on the physical board.

Current production distance is `max(abs(Id-reference_Id), abs(Iq-reference_Iq))`.
The reference is the last TRUSTED accepted dq pair, not necessarily the previous
RAW pair after a suspect. Polarity was already accounted for; increasing the
threshold is a deliberate tolerance change, not repair of a missing-sign bug.
For either axis, -75 ->+75mA is150mA, -100 ->+100mA is200mA and admitted;
-150 ->+150mA is300mA and quarantined. Reverse-direction behavior is identical.
This is NOT `abs(abs(current)-abs(reference))`, which would hide sign reversals.

The same existing threshold also governs return-to-trusted and candidate-cluster
coherence, so those tolerances become200mA too. First-suspicion quarantine before
either DOB LPF,3coherent-point qualification, short-gap state retention and
invalid recovery frame,10ms long-gap recovery,60mA/20ms sustained filteredId
gate and ~398ms ordinary warmup remain. No FOC feedback, PI, limits, phase,
angle, PWM pipeline, current discriminator, encoder/IRQ or motor protection
change. DOB remains observation-only. Higher tolerance may admit more noise;
availability, model accuracy and closed-loop benefit are not measured here.

## Changed files

- `foc2_app_a/CMakeLists.txt`: opt-in A-only200mA switch, requires pre-LPF policy.
- `foc2_app_a/CMakePresets.json`: separate configure/build preset to preserve
  historical frozen images and provenance.
- `tests/dob_id_pre_lpf_200_host.c`: actual monitor/admission/trace native tests.
- `tests/test_dob_id_pre_lpf_200.py`: native/protocol/build/control equivalence.
- This document.

## Compilation and focused validation

A configure/build PASS,216620B image, static RAM130704/131008B (304B remaining).
Existing unused-function and RWX linker warnings remain; no stack/heap shrink.
B review build reports no work; its BIN SHA256 remains
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
Physical stable B was not accessed or changed.

New A BIN SHA256:
`5bd9e2c52ffaeecf70d8c0b35f981b90e0bfa250aa3ae39620f2a5b411346301`.
New A ELF SHA256:
`eba0c08a3b8c76bee758570fe88b077ee89c18a05c69d660640b8cf6072930a3`.
Build log:`tmp/dob-pre-lpf-200-build.log`.

Four focused tests PASS. Actual production C at both-Os/-O2 with
-Wall/-Wextra/-Werror verifies both axes/directions, exact200mA equality,
>200mA exclusion, isolated+/-700mA spikes do not alter either LPF/warmup or
reset the observer, qualified return/following-frame validity, coherent
sustainedId still detected at20ms, one10ms-gap reset/recovery, real fault exit.
Actual readonly protocol reports JUMP_UA=200000, ID_MAX_UA=60000, ID_US=20000,
CONFIRM=3, REF=TRUSTED, GAP_US=10000, LATCH=0, FEEDBACK=0.
Preprocessed FOC/current/speed/angle/IRQ/power/guard/task functions compare
identical against V7. Historical V7 BIN hash remains unchanged.

An initial new host test omitted trace After/Lifecycle bookkeeping, causing an
incorrect reset-counter assertion; its harness was repaired (no production
algorithm change), then focused native tests PASS. Combined discovery also
exposed old board-wrapper import-time shared module configuration contamination
(six-point test sees single600rpm profile). Those test modules were run
in separate Python processes, matching their standalone entry points, rather
than changing historical hardware wrappers or accepting contaminated tests.

Final isolated regression:39modules,183tests, ALL PASS (including the four new
tests), log:`tmp/dob-pre-lpf-200-isolated-regressions.log`. This covers DOB,
mechanical diagnostics,Id statistics, encoder completion/admission, readiness,
outer-loop completion, PWM pipeline and current admission/protection modules.
No motor experiments were performed and no real-time availability improvement
is inferred from these offline tests.

Subsequent separately authorized board test and restoration are recorded in
`docs/dob-pre-lpf-200ma-board-20261023.md`; the offline results above are not
retrospectively relabeled as hardware tests.
