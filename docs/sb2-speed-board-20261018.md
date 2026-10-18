# SB2 no-load board acceptance — 2026-10-18

## Result

**Speed acceptance FAIL; timing/zero preflight PASS.** One START only. The host
planned a 20 rpm, approximately 2 s no-load SPEED observation. At host time
0.933 s it observed stage 2 / CONTACT_STOP, and stopped rather than continuing
through the torque stages. This is not a protective fault or a complete cycle.
No second START or automatic retry was attempted.

The user confirmed drive OFF for staging, MCU powered, motor connected/fixed
and no-load, IU→PA0, IV→PA1 and PC6→CTRL_SD unchanged. Before execution the user
confirmed drive ON with no alarm and immediate power-off available; the agreed
supply setting was 12 V / 0.5 A. After capture the user confirmed 12 V OFF.
These are operator confirmations, not independent power/shaft measurements.

## Exact identity and receipts

- A preset: `SpeedBumplessTrial`, BIN 228500 bytes.
- BIN SHA256: `b78864f64ff417d4cfc3101f9d6f22292a96e89807359f4154aa8ee6ba0f8488`.
- ELF SHA256: `e214429a993cd852affdf5a3d849c35a51740c79fe108b601a5bb3c8ad314110`.
- Stage: `tmp/sb2-speed-stage-1792312070970048100.json`.
- Run: `tmp/sb2-speed-speed-1792312170760143300.json`.
- Restore: `tmp/sb2-speed-restore-1792312229610595100.json`.

Full staged readback verified inactive A and all bytes outside its erased page
range. B649, bootloader and private/configuration bytes were preserved. The
existing bootloader trial and 5 s health confirmation completed normally,
including the confirmation reset; the resulting A generation was 652.

## Measured results

| Item | Result |
|---|---:|
| Accepted zero pairs | 4000 |
| Rejected / total zero collection | 52 / 4055 |
| Maximum consecutive zero rejects | 1 |
| Zero U / V | 1559 / 1563 |
| FOC wall maximum, startup + motion | 29.3412 µs |
| >50 µs deadline misses | 0 |
| Actual CCR commits | 154960 |
| Actual CCR late commits | 0 |
| Actual minimum CCR margin | 15.1529 µs |
| CUR_CONFIRM enter / clear / fault | 59 / 59 / 0 |
| First protective fault valid | 0 |

Selected UART observations (host-relative time, encoder-derived speed):

| Time, s | Stage | CTRL rpm | Iq demand, mA |
|---|---|---:|---:|
| 0.150 | RUNDOWN | 0.0 | 87 |
| 0.629 | RUNDOWN | 0.0 | 277 |
| 0.689 | RUNDOWN | 0.4 | 300 |
| 0.874 | RUNDOWN | 0.2 | 376 |
| 0.933 | CONTACT_STOP | 0.6 | 0 |

The preserved 1 kHz speed diagnostic interval was 0.9000302 s. Its filtered
speed range was -0.8039 to +1.0069 rpm; mean was 0.09294 rpm. This does not
establish independent shaft speed, but confirms that the controller did not
observe sustained 20 rpm tracking. Do not label the sparse UART maximum as the
full-rate maximum. The final 32-frame startup ring crosses the SPEED→IDLE
transition, so its whole-ring average Iq cannot be used as running current
tracking evidence. It contains only a short pre-transition window.

## Why the host stopped

The existing, unchanged `TighteningTask` declares contact when its detection
speed is at most 10 rpm and q-axis **current demand** is at least 300 mA for
250 ms. It then sets IDLE and moves to CONTACT_STOP. This condition does not
require measured physical contact or measured torque.

In this run demand increased while speed remained near zero, satisfying that
existing condition. The no-load speed runner detected departure from SPEED,
sent STOP, latched ANALOG SAFE, verified SD=0/MOE=0/FOC=0, restored RUNDOWN_RPM
to 70 in RAM without SAVE, and captured Flash/SRAM while halted.

Given the operator-confirmed no-load setup, this is an apparent contact
classification of a low-motion/high-demand startup, not proof of real workpiece
contact. SB2's faster I rise can reach this existing condition earlier than SB1;
this is an interaction to investigate, not evidence that thresholds should be
raised or the stop should be bypassed. The original cause of poor breakaway
(actual phase current, phase/angle correspondence, supply behavior or mechanical
resistance) remains unresolved. The run did not exercise SB2's overspeed unload
behavior because there was no comparable speed rise.

## Host changes and offline checks

No firmware source, controller parameter, protection threshold or state-machine
logic changed during this board-test task. Added an exact SB2-specific host
stage/trial/restore runner and seven no-device tests. The existing SB1 motion
helper accepts an expected controller marker argument, defaulting to SB1; its
timing/stop/protection checks are unchanged. SB2 requires its own BIN/ELF pins.

- New host runner tests: 7 PASS.
- Existing SB1 host runner tests: 11 PASS.
- SB2 algorithm/integration tests: 13 PASS.
- The prior full-suite 9 failures / 4 errors were not repaired or rerun here.

## Final state

After the user confirmed drive OFF, the existing bootloader mailbox restored
the original confirmed B selection, generation 653, no pending trial and zero
attempts. A hardware breakpoint stopped execution before B application
instructions. Final SD=0, BDTR=0, CCER=0, MCU halted. Application and private
bytes remained unchanged during trial/restore. SB2 remains in A but is not the
selected startup slot. No additional motion or test was performed.
