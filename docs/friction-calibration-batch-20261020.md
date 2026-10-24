# Running-friction calibration diagnostic A (2026-10-20)

Purpose: identify unloaded effective running-friction current, not calibrated
shaft torque and not static breakaway current. User requested a consolidated
supervised experiment. No automatic current escalation or production parameter
write. Stable B remains untouched.

## Fixed acquisition plan

- FRIC OFF, acceleration FF ON with unchanged Ka; fit only final reference with
  zero acceleration. Original S-curve, speed/current PI and limits unchanged.
- Speeds: +40,+80,+120,+240,-40,-80,-120,-240 rpm. Three planned repetitions.
- One point per boot. Explicit FCAL command only; ordinary START cannot launch
  the diagnostic. Five-second driven interval, then S-curve to zero; normally
  stop after 100ms under 2rpm or forcibly close outputs at 7s. Existing independent
  12s lease, 300rpm trip, +/-0.50A command limit and all ADC/current/encoder/timing
  protections remain. Existing rundown no-rotation guard is reused; 20000-degree
  travel bound retained. No CONTACT/tightening stages in this measurement owner.
- Independent normal reset/calibration before every point, not fault clearing.
  Any preflight, hardware/protection, deadline/CCR margin or communications
  failure aborts the entire batch. No retry of a failed command.
- A normally stopped but nonqualifying speed plateau is preserved as invalid;
  other predetermined points can still be acquired. It never causes an automatic
  current increase. Planned repeats are not fault retries.

## Evidence, not new protection thresholds

`friction_calibration.h` criteria are measurement-admission criteria only:

- speed within max(2rpm,5% command), final S-curve reference and zero acceleration;
- 500ms speed stability before accumulation, at least 2s admitted samples;
- no saturation, current discriminator normal and protection clear at observation;
- ADC sequence checked around the dq snapshot without masking interrupts;
- retain rejected count; >5% rejected versus admitted+rejected disqualifies point;
- no sample interpolation, new feedback filter, current/PI change or ISR logging.

MotorControlTask accumulates time-weighted Iq, IqRef, Id, |Id|, Iq squared,
speed/error and travel. Binary aggregate is 84 bytes; existing FRC compressed
logs remain enabled. This is 1kHz outer-task evidence, not a full 20kHz raw-ADC
oscilloscope record. Sequence-mismatched/rejected readings are not included in
the current averages. Underlying current gain/physical phase mapping must still
be trusted to interpret the result as friction current.

The Python report flags poor mean Iq tracking, substantial Id and noisy current
feedback rather than silently fitting those points. At least two matched signed
speed magnitudes are required to fit:

`mean Iq = bias + Coulomb * sign(speed) + viscous * speed_rpm`.

Fewer than all 24 clean points is explicitly incomplete coverage. Positive and
negative extrapolated intercepts are reported, but sensor bias and asymmetric
mechanical load/friction cannot be uniquely separated by this model alone.
Negative fitted friction/damping or substantial residuals require review. No
result is written to I_FRIC, deadband, PI, electrical zero or Flash parameters.

## Files / commands

- `firmware_common/friction_calibration.h`, `friction_calibration_binding.inc`.
- A-only optional wiring in main/CMake/presets and existing protected command /
  original admission adapter; normal builds compile the branch out.
- `tools/friction_calibration_board.py` default is files only; separate OFF
  staging / supervised powered batch / OFF B-selection restore modes.
- `tools/friction_calibration_report.py` offline fitter; tests under
  `tests/test_friction_calibration*.py`.

Diagnostic preset: `FrictionCalibrationDiagnostic`, default FRIC OFF.

Image size 212836 bytes; RAM 129040 / 131008 bytes (static linker occupancy is
not usable task-stack space). BIN SHA256
`a23a7c8760e92cd498d3753065aad12a220ce66514aeac245421869a24a117f0`;
ELF SHA256
`8a392f5d7ffb72b5849b3b4713c5d1ac5f311b237484b462d9ff28a005e207ee`.

Formal FR1 A rebuilt byte-identical, BIN
`c8c7a7e9e0753e6d39aadaddcd038df3c3f943aa0f3d167397662ac615d015f8`;
B rebuilt byte-identical, BIN
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.
Diagnostic build retains existing RWX/unused warnings and has additional unused
original FSM helpers because the diagnostic task replaces the tightening owner;
there are no final link errors. Initial build failed for two missing status/
precheck adapter definitions; repaired before any staging. Native regression
initially caught unsigned arithmetic in the test's negative-angle fixture;
the fixture was corrected, not the controller.

Offline: 73 combined diagnostic/existing regressions, 8 FR1 regressions and
14 old board-runner tests passed. Final updated diagnostic/report/runner group:
12 tests passed. Actual ADC/FOC math, safety, IRQ and PWM pending functions are
preprocessor-compared against FR1; only an outer-task diagnostic observe call
was added. Both original A/B hashes remain unchanged.

## Hardware preparation

After a fresh combined OFF/empty-fixed/operator-present confirmation, inactive
A staging and independent full readback passed:
`tmp/friction-cal-stage-1792488385414135500.json`.
No application activation or motor command during staging; B/boot/config and
metadata preserved. Powered execution has a separate current-session receipt;
no old test values may be substituted for this new diagnostic's timing/results.

## First supervised attempt: pre-motion client refusal, no motor test

User confirmed powered/no-alarm and present. Batch receipt
`tmp/friction-cal-run-1792488465624744200.json`, first-point receipt
`tmp/friction-cal-run-1792488465624744200-00.json`.

The newly compiled A completed normal health confirmation/reset and zero
calibration, but the inherited read-only startup console rejected the first new
read-only FF/FRIC/FCAL status query. Error:
`Read/stop only; original START uses separate bounded runner`.
This is a host command-whitelist defect, not a friction or motor fault. No FCAL
RUN/START command was sent. The batch aborted before motion, did not retry and
saved same-session Flash/RAM with SD/MOE/CCER OFF and MCU halted.

This output-OFF interval measured FOC max 29.888us, deadline miss 0, actual CCR
commits 27367, late 0, min margin 16.682us; CUR_CONFIRM 9 enter/9 clear/0 fault.
These values are **not a powered-motion or friction-calibration result**.

After user confirmed 12V OFF, normal mailbox B selection restoration passed:
`tmp/friction-cal-restore-1792488545378976100.json`, generation 784, confirmed B,
no pending/attempt. B/application/boot/config preserved; B application not run,
halted at entry, SD=0/BDTR=0/CCER=0. Full Flash SHA256
`6471b5ab00ae66af1e5d94b781c2aed479b771cbaeb150fff209e619a3cbd055`.

The isolated calibration console now permits exactly three additional
**read-only** status queries, without widening historical whitelists or permitting
motion via that read channel. Added real-console regression proves FCAL RUN,
START, FRIC ON and SAVE remain denied there. Full restoration identity is
validated before accepting generation784 as a new staging baseline. Final
diagnostic/report/runner tests: 14 passed. No firmware rebuild/change was needed
for this host fix, no second trial or motor start occurred. A remains an inactive
calibration candidate. Await a new manual retry request.

## Manual retry: first +40rpm point trips existing NO_ROTATION

User explicitly requested retry. Fourteen diagnostic/report/client tests passed;
inactive A re-staging/readback passed without changing the image:
`tmp/friction-cal-stage-1792488687368193100.json`. User separately confirmed
12V ON, no alarm, 0.5A supply limit, empty fixed motor and operator present.

Batch receipt `tmp/friction-cal-run-1792488721172564400.json`, point 1 receipt
`tmp/friction-cal-run-1792488721172564400-00.json`. Actual FCAL +40rpm command was
accepted and powered motion occurred. At about 3.680s the retained rundown
startup guard stopped it: first fault valid=1, domain=3 PROCESS, reason=7
NO_ROTATION. The guard requires established motion, not literally zero encoder
travel. No later speed point, direction or repeat was attempted.

- Driven 1kHz observations: 3680; valid steady samples 0, reject 3243. Rejection
  includes failing the 40+/-2rpm stable-window requirement; this is **not** a count
  of ADC spikes and not the runtime current-discriminator reject counter.
- Net observed mechanical travel +145.722656deg; total absolute travel
  285.205078deg (ratio about1.96). Short motion and reversals are not steady
  rotation at the target speed.
- Sparse10Hz FRC speed observations (37) min -9.322, max86.322, mean8.204rpm.
  These are not full-rate peaks or a qualified steady-state average.
- Late samples: at3.303s speed0.307rpm, IqRef0.252995A/Iq0.252750A;
  3.403s speed0.292rpm, IqRef0.293051A/Iq0.283750A;
  3.503s speed1.303rpm, IqRef0.330007A/Iq0.325220A;
  3.603s speed1.072rpm, IqRef0.370713A/Iq0.400920A.
- First-fault capture is after output closure: IqRef=0 there must not be
  interpreted as the pre-trip requested current. Capture Iq0.360687A,
  Id-0.030497A, filtered speed0.683177rpm, raw speed-11.041535rpm.
- Zero admission PASS:4000valid/42reject/4045total, max consecutive1,
  offsets1560/1564. Encoder valid1/errors0; current unresolved max consecutive1.
- FOC max31.57647us, deadline0; actual CCR205471, late0, margin15.15882us.
  CUR_CONFIRM75enter/75clear/0fault. Motor-task free stack2564B.
- SD=0, MOE/AOE bits=0, CCER=0, MCU halted. Remaining non-enable BDTR bits
  were preserved (not claimed as an all-zero BDTR register).

This is a failed motion-establishment point, not an identified Coulomb current.
No automatic compensation write, PI/limit change, upward current or point retry.
Need a later separately authorized plan, potentially starting at a previously
stable speed and evaluating low-speed stick-slip independently; cannot assume
that software Iq tracking alone proves physical torque or friction magnitude.
Operator has been asked to close12V before original B-selection restoration.

Operator subsequently confirmed12V OFF. Original B selection restored normally:
`tmp/friction-cal-restore-1792491242366781600.json`, generation788, confirmedB,
pending/attempt0. Full readback/preservation PASS, B application not run, MCU
halted at B entry, SD=0/BDTR=0/CCER=0. Full Flash SHA256
`9e6c037d5dd59224486c95f9397d9a23e9ce7fddffdc6817b3ce11f8d2a01e11`.
No further tests performed. A diagnostic remains inactive. Any later staging
must explicitly use this new restore receipt with `--baseline-restore`; the
default generation784 baseline is historical and must not be silently reused.

## Revised batch continuation policy (explicit user request)

User requested retaining failed measurements and continuing the other points,
instead of aborting the grid for an isolated non-motion point. Host-only change:

- Single-point NO_ROTATION remains a failed point; firmware guard, timing,
  thresholds and image are unchanged. Do not clear a live fault or continue the
  same energized session. Stop/ANALOG SAFE, halt, save Flash/RAM, verify all
  outputs OFF, then use a new normally calibrated protected boot for next point.
- The sole nonfatal first fault is exact PROCESS(domain3)/NO_ROTATION(reason7),
  with protection_flags0, encoder valid, qualified timing, no CUR_CONFIRM fault,
  explicit queued command/terminal proof and no later live guard fault.
- Stopped RAM is separately decoded for cl_flags/cl_fault_valid/adc_fault/
  foc_fault/encoder_valid, preventing an earlier process first-fault snapshot
  from hiding a newer hardware/current/encoder fault. Real safety faults, bad
  timing, uncertain ACK/stop or missing evidence still abort the grid.
- Failed points retain travel and explicitly sparse speed/Iq log statistics;
  they are never used as steady Coulomb-current measurements or replaced by0.
- Resume verified completed +40rpm measurement1 from the prior receipt, then
  acquire the other23 planned points. Three preplanned repetitions remain;
  no extra retries or current escalation. First new +80rpm point alone submits
  a normal A trial; subsequent points reset the same confirmed A.

Eighteen diagnostic/report/client regressions passed, including exact saved
NO_ROTATION classification, every guard/timing exclusion, legacy read whitelist,
fault-stop policy and resume/initial-activation semantics. Firmware BIN/ELF,
formal A, stable B and protection parameters unchanged. Independent inactive-A
staging/readback passed without programming:
`tmp/friction-cal-stage-1792491573967300000.json`.

上述策略随后实测完成24段（复用首段+新采23段），未因单点NO_ROTATION停组。
结果、质量判据、全部速度/Iq对照、时序及generation792恢复证据见
[24段完整对照](friction-calibration-24-point-results-20261020.md)。
最终原B已恢复且停在入口，12V关闭；本轮没有自动追加测试或写入补偿参数。
