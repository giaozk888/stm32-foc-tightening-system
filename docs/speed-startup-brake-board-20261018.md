# SB1 board trial, 2026-10-18

Result: startup zero calibration failed before normal FOC or SPEED control.
No START command was sent. The SB1 speed-loop behavior has not yet been
validated on the motor; this run is not a speed-control acceptance pass.

## Programming and startup

The exact offline-tested A image (229316 bytes, SHA256
`98a90620404a9daa1210f7f8e61aa9cbda6b8d612b8a884cc6d83a950e25f50f`)
was programmed only into inactive A while the user-confirmed 12 V supply was
OFF. Full 512 KiB readback comparison passed. B634, bootloader, configuration
and metadata were unchanged during staging.

After the user confirmed 12 V ON, no alarm and immediate power-off readiness,
one normal bootloader trial was submitted for A. At the first application
startup, the zero estimator failed. The script did not send START, confirm
the failed trial, clear a fault or automatically repeat activation.

First fault: protection flags=8 (CL_BAD_ZERO), IDLE mode, tightening state 0,
ADC sample count=23125, normal FOC execution count=0. Final status flags=12
include the downstream ADC lock as well as zero failure. The first cause was
zero quality, not an observed SB1 brake or speed-controller fault.

## Exact zero failure

The saved RAM was decoded against the exact candidate ELF. ARM compiler
layout was checked rather than assuming host enum sizes: FocZeroState and
FocZeroReason are 1 byte, FocZeroCal is 72 bytes, FocZeroRobust is 56 bytes,
and the robust block is at the tail of the 172-byte zero-filter object.

- State: FAILED; reason: UNSTABLE.
- Settled: 20000 physical ADC pairs.
- Accepted zero collection: 3120 / 4000 pairs.
- Nominal: 1561 ADC counts.
- Collected median ranges: U=1552..1566; V=1553..1570.
- Robust flags: 4, FOC_ROBUST_BURST.
- Completed segments: 6; observed outlier total: 43 (diagnostic count).

The final five physical pairs were:

| Pair | U raw | V raw | Distance from U median 1564 | Distance from V median 1570 | Existing pair decision |
|---:|---:|---:|---:|---:|---|
| 1 | 1564 | 1570 | 0 | 0 | inlier |
| 2 | 1535 | 1526 | 29 | 44 | rejected by V |
| 3 | 1565 | 1570 | 1 | 0 | inlier |
| 4 | 1625 | 1646 | 61 | 76 | rejected by U and V |
| 5 | 1561 | 1567 | 3 | 3 | inlier |

The existing combined pair predicate rejects if either channel differs from
its own five-point median by more than 40 counts. Two rejected pairs in one
five-pair block trigger the existing burst check (`rejected > 1`). This
accounts exactly for the captured flag; neither nominal offset nor segment
drift was the recorded trigger. No zero-quality limit was changed.

## Timing interpretation

The outer ADC IRQ maximum captured during startup was 16.5118 us, with zero
deadline misses. However, normal FOC execution and actual CCR commits are
both zero. Consequently no new normal-FOC maximum or actual PWM commit margin
can be reported from this failed startup. Zero-filled margin storage is not
a measured zero margin.

## Shutdown and recovery

The failure cleanup shut down SD/MOE/CCER and halted the MCU. The user then
confirmed 12 V OFF. Complete RAM and Flash were saved before any reset.

The existing bootloader SET_CONFIRMED_SLOT mailbox selected the already
confirmed B image. The CPU stopped at B Reset_Handler before B application
instructions ran. Final metadata generation=637, confirmed B, no pending
trial, no remaining trial attempts. Full capture comparison verified all
application/private bytes unchanged by recovery. A retains the staged SB1
candidate, but is not selected to boot.

Ignored local evidence:

- `tmp/speed-startup-brake-stage-1792302803143371000.json`
- `tmp/speed-startup-brake-trial-1792302869956762700.json`
- `tmp/speed-startup-brake-trial-1792302869956762700-ram.bin`
- `tmp/speed-startup-brake-zero-failure-20261018.json`
- `tmp/speed-startup-brake-restore-1792302971513816100.json`

Next board acceptance still needs a successful normal-supply zero startup,
then SB1 timing preflight and one protected SPEED/FSM trial. No such repeat
was performed in this run.
