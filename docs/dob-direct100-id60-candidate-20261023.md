# Candidate A: direct100mA dq jump exclusion, filtered abs Id60mA admission

User explicitly chose adjacent Id/Iq jump threshold100mA and requested Id upper
limit0.06A. In the context of the DOB gate discussion this means changing the
new candidate's `abs_id_lpf` model-domain admission threshold50→60mA, NOT changing
IdRef, instantaneous physical Id safety, motor current limit or hard overcurrent.
This interpretation was stated to the user before implementing it.

## New isolated profile

`MechanicalDobDirect100Candidate` inherits `MechanicalDobAdmissionStartGuardCandidate`
with opt-in/default-OFF `FOC_DOB_DIRECT_JUMP_REJECT=1`. Requires the guarded DOB
diagnostic. No change to formal B; previous V1/V2/V3 candidates remain hash-pinned.

## Exact data-admission rule

After the unchanged one-way motion qualification (existing20rpm minimum,
same-sign50ms), compare the current dq pair to the last ACCEPTED actual pair:

    jump = max(abs(Id_now - Id_last_accepted), abs(Iq_now - Iq_last_accepted))
    if jump > 0.100 A: immediately exclude this WHOLE pair

Exactly100mA is allowed (subject to original other quality checks).
The reference is last accepted, not last raw/rejected pair: this prevents a
discarded excursion becoming the reference which makes the next return fail.
The user was informed of this explicit reference choice.

- No pending-candidate, wait-for-return, isolated-spike confirmation or persistent
  transition classifier runs in this profile. Rejection occurs on THIS call.
- Raw Id/Iq remains recorded as evidence; the rejected pair enters neither Iq
  LPF nor LPF(abs(Id)), nor the observer dynamics. Reference/LPFs/warmup remain
  unchanged on an isolated rejection, no observer reset on that rejection alone.
- That epoch's DOB output is INVALID, matched-current/output estimate0, not an
  old sample falsely presented as fresh. Raw current remains visible in the frame.
- A later actual pair within100mA of the accepted reference can pass immediately.
  There is no separate return-tolerance test and no retrospective spike label.
  The accepted endpoint uses the actual bounded<=2500us gap; this is an explicit
  endpoint approximation, not interpolation of missing current. The GAP_RECOVERY
  epoch also remains invalid and earns no warmup credit. Next normal point can
  qualify again using accumulated pre-gap warmup.
- Existing bounds remain: second consecutive rejected/held epoch exits DOB
  observation; fifth hold per32-observation window exits; accepted gap>2500us
  exits. Exits are latched, no auto-rearm/retry. A sustained genuine current step
  is NOT silently rebased or ignored forever and will fail these bounds.
- Original raw/saturation/time/sequence/current-validity checks run first,
  unchanged. Motor protections still see raw data independently of this branch.
- Pre-arm, STOP/fault, one-way arming and shadow-only/no-Iq-feedback remain as V3.

## Id gate requested by user

Only with `FOC_DOB_DIRECT_JUMP_REJECT`,
`DOB_MONITOR_MAX_FILTERED_ABS_ID_A=.060f`; all previous profiles stay.05f.
This gate is applied after accepted-data LPF updates. Strict >60mA resets the
observer via the existing ID-quality path; equal60mA does not. This is not a raw
|Id| clamp: an instantaneous raw Id value can exceed60mA if other quality/admission
allows it, and filtering/safety have their respective original roles.
No speed/current PI, IdRef, Iq limit, voltage limit, phase/current mapping, angle,
S-curve/FF, CUR_CONFIRM, CURRENT_INVALID, hard OC,20kHz FOC, PWM or IRQ changes.

## Diagnostics

V4 binary trace keeps48B/frame,16 pre +32 dense post +48 decimated tail=96frames,
same4608B backing buffer, raw signed Id/Iq, ADC sequence/source/publication time,
mechanical time/reference/speed, actual LPF, warmup, reset and decision/exit reason.
First DIRECT_REJECT triggers capture without waiting for steady state.
New decisions10=DIRECT_REJECT and11=GAP_RECOVERY are explicitly invalid; no
legacy SUSPECT/SPIKE_RETURN/TRANSITION/UNRESOLVED decision is valid in V4.

Readonly config is explicit and fits the original192B reply buffer:

    MOTOR TEST MECH DOB ADMIT CFG
    MODE=DIRECT JUMP_UA=100000 ID_MAX_UA=60000 REF=ACCEPTED ... FEEDBACK=0

It no longer misleadingly reports unused RETURN/CONFIRM thresholds.
The old SUS stats counter records direct threshold exclusions in this profile;
isolated/transition/unresolved counters are not confirmations and remain0.
V1/V2/V3/V4 decoder distinguishes policies and50/60mA ID gates. Historical board
captures retain provenance checks and are not reinterpreted as new measurements.

## Offline evidence and limits

Native C -Os/-O2 checks cover exact100mA equality, >100mA, positive/negative Id
and Iq jumps, paired/reference/filter freeze, no reset or warmup credit on a
single exclusion/recovery, no fake validity, no legacy transition/spike label,
preserved consecutive/rate exits and no re-arm,60mA equality and61mA ID rejection,
bad current/fault/STOP, V4 buffer canary/ABI/decoder/protocol, and frozen control paths.

Replay of ONLY48 retained dense dq rows from
`tmp/mechanical-ident-run-1792724932372082300.json`, seeded at the first retained
pair (NOT full-session observer/arming state), gave4 direct exclusions and4 gap
recoveries without an admission latch in that short segment. At the former first
event, the -1ms larger pair is excluded immediately, the0ms return is gap recovery,
and the+1.001ms point is normal instead of causing transition/reset.
This is useful regression evidence but does NOT prove physical noise, full-run
valid coverage, successful DOB or a future protection-free board result.

## Build identity

A Flash215408B; RAM130616/131008B (392B spare), no heap/stack reduction.
BIN SHA256 `505b9661bf96ccddef40d647b9c18c1df333daa3ae580fdf61c8a9c4bf617e36`.
ELF SHA256 `613bf59193fb1f82f8daa16b8362ab62c210c57be9c96997ef779aa1cf989814`.
B review build passed, BIN unchanged
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
Existing unused/RWX warnings remain; no new main warning class relative to V3.
Six new test methods PASS. All144 related regressions PASS, recorded in
`tmp/dob-direct100-regressions.log`.

## Hardware status

No debugger/hardware access, programming, activation or motor commands this turn.
Last physical board state remains original B selection under
`tmp/mechanical-ident-restore-1792725093959340300.json`, stopped/output-off after
user-confirmed12V OFF. New V4 needs its own exact-image-pinned harness and fresh
physical OFF/ON confirmation before future single-run validation; old V3 harness
must not be weakened/reused by removing identity gates. Do not claim board success.
