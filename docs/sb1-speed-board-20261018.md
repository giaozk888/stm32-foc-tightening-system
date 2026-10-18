# SB1 + robust zero: actual 20 rpm speed acceptance, 2026-10-18

Subsequent RAM analysis: [detailed tracking diagnosis](sb1-speed-tracking-diagnosis-20261018.md)
finds a retained1kHz filtered-speed maximum of31.04rpm. The17.8rpm below is
only the sparse UART maximum, not the actual maximum seen by the speed loop.

## Outcome

One real START was acknowledged, SPEED mode ran, and STOP completed. No
protection fault occurred. However, **speed tracking did not pass** the
provisional final-half-second20±5rpm test. This is not a full tightening or
industrial speed/torque qualification.

The motor was user-confirmed connected, no-load and fixed, with the existing
12V/0.5A supply setting and immediate power-off available. No firmware was
programmed. Exact already-verified A image ZeroValidAdmissionTrial (SB1) and
all current/speed/timeout protection thresholds remained unchanged.

## Preliminary host-script correction

The preceding no-START attempt ended because the host waited only1.5s for
timing reports. MonitorTask's actual print interval is5000ms; the firmware
does print these reports. The statement that the image did not print them
was incorrect. The host now waits at most8s, checks READY/output-off during
the wait, and refuses missing/partial/failing timing. No firmware logging or
timing/control algorithm was changed to accommodate the script.

Host phase receipts are atomically replaced after flush/fsync, including
before START intent, ACK, feedback, STOP and final output-off. This is evidence
durability, not an independent motor stop mechanism. The original board lease
remains12s; the2s test is a host STOP deadline, subject to host scheduling.

The no-START attempt receipt is
`tmp/sb1-speed-speed-1792310000692732600.json`.
The actual speed-run receipt is
`tmp/sb1-speed-speed-1792310227239040200.json`.

## Measured response

32 UART speed samples were recorded. All speed/position values below are
encoder-derived, not independently measured shaft speed.

| Time after START, s | Filtered rpm | Iq reference, mA | Position, degrees |
|---:|---:|---:|---:|
| 0.139 | 0.2 | 78 | 0.04 |
| 0.634 | 0.3 | 176 | 0.39 |
| 1.123 | 0.2 | 275 | 1.05 |
| 1.248 | 14.7 | 255 | 5.60 |
| 1.307 | 17.8 | 1 | 14.58 |
| 1.367 | 1.6 | 62 | 14.74 |
| 1.986 | 0.3 | 190 | 18.06 |

- Target20rpm; highest **sampled UART** filtered speed17.8rpm.
- Last0.5s mean filtered speed0.4rpm; maximum target error20rpm. Not tracking.
- Position progressed to about18.3degrees, but encoder feedback alone does
  not establish phase alignment, actual torque, or independent mechanical speed.
- No overspeed trip occurred. Sparse UART samples do not exclude a short
  between-sample overshoot, so this is not proof of zero full-bandwidth overshoot.
- START commands1, acknowledged request7830. No automatic second START.
- First STOP send was about2.01s after START; ACK about2.0205s. Do not claim a
  sub2.000s hardware-enforced stop from this host-controlled measurement.
- First post-STOP status: IDLE, BUSY0, STOPPED, FLT0, encoder speed0.2rpm,
  Iq reference0. Stop feedback check passed.
- ANALOG SAFE confirmed latched1, SD0/MOE0/FOC0. Temporary recipe rpm20 was
  restored to original70 in RAM; no SAVE was sent, and full Flash was unchanged.

The startup-to-motion trace shows slow current-reference buildup, a short
speed rise, a rapid reference reduction, and loss of speed. This is evidence
of unsatisfactory startup/tracking, not proof that a particular PI parameter,
phase mapping, friction, supply limit or encoder issue is the sole root cause.
No parameter or protection was changed after observing the response.

## Zero, timing and protection

| Statistic | Actual value |
|---|---:|
| Accepted zero pairs | 4000 |
| Rejected / physical collection | 43 / 4045 |
| Max consecutive zero rejects | 2 |
| Zero U/V | 1560 / 1563 |
| FOC wall max, startup + motion combined | 28.9176us |
| >50us deadline misses | 0 |
| Actual CCR commits | 175653 |
| Actual CCR late | 0 |
| Actual minimum margin | 15.1824us |
| CUR_CONFIRM enter / clear / fault | 87 / 87 / 0 |
| Immutable first-fault valid | 0 |

This run does not reproduce the earlier idle CURRENT_INVALID. It must not be
called permanently fixed; it simply did not occur during this bounded run.
The failed speed criterion is a host acceptance result, not a firmware trip.

## Final state

After the user confirmed12V OFF, existing bootloader selection restored the
original unchanged B and halted before B application instructions. Final
metadata generation649, confirmedB, pendingnone, attempts0. SD=0, BDTR=0,
CCER=0; MCU halted. All application/private bytes were verified unchanged.
New A remains in Flash but B is selected. No further motor run was attempted.

Recovery receipt:
`tmp/sb1-speed-interrupted-restore-1792310314390233000.json`.

The host script's11 no-device tests pass, including5s report arrival,
missing/partial/fault rejection, durable START intent and failed-journal
refusal, single START, cleanup, unchanged recipe and nonfinite feedback.
Firmware kernel tests passed previously; no firmware build or source change
was needed for this measurement.
