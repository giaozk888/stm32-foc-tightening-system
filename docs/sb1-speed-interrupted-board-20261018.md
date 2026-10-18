# SB1 speed acceptance attempt: interrupted, not a motor acceptance PASS

## Result

No new speed-loop motor response was acquired. Do not claim that SB1 passed or
failed a running-speed test. The foreground test process/session disappeared
without its final JSON receipt. The exact point and cause of host interruption
cannot be reconstructed from the available host artifacts.

The only artifact from the original run is
`tmp/sb1-speed-speed-1792305950527865700-before.bin`. No START telemetry,
2-second speed series, stop-time series or completed runner receipt exists.
No automatic reactivation or second START was attempted during recovery.

## What the recovered board evidence actually proves

The saved full Flash matches the exact ZeroValidAdmissionTrial/SB1 A binary
(228428 bytes, SHA256
`11b99efb2323f552b568bb3e8dcbf2f1e0cab5257bd81f15816be2fad475e7e6`).
The matching ELF SHA256 is
`ba3bcde75abfbdc73b6184368e6f860be91c7024877155f479a91597df28f889`.
Normal health confirmation completed; recovered metadata generation was644,
confirmed A, no pending or remaining attempts.

Decoded against that ELF:

- `ClSession.state=CL_FAULT`, `used=0`, `queued=0`, `started=0`, `start_us=0`.
- Startup trace has zero completed rows and `start_us=0`; it was frozen by the
  later fault, not by a started motion session.
- The immutable first fault occurred at553784ms (about553.8s after boot),
  with motor modeIDLE, tightening state0, speed reference0, Iq reference0.
- Protection domain2, reason11=`FOC_FP_CURRENT_INVALID`.
- TWO_SAMPLE unresolved consecutive=3, maximum consecutive=3. Therefore the
  recorded event is a runtime current-validity failure in idle, not overspeed,
  zero-calibration failure, current PI instability during motion, or a deadline
  miss. Why those three samples were unresolved cannot be determined from this
  end-state alone; no pre-decision per-frame trace was enabled in this image.

The unused session and empty startup trace are strong board evidence that the
application never admitted START during this boot. Because host command logs
were lost, they are not independent proof of every byte the host attempted to
send. No motor movement is inferred from the near-zero idle speed.

## Zero and timing are separate observations

Recovered zero calibration: READY, reason0, 4000 accepted pairs,48 rejected,
4050 physical collection pairs, maximum consecutive reject1, zeroU/V=1560/1563.
The two remaining physical pairs are unused tail pairs from the final median
block. This remains a successful zero result, not a speed-loop acceptance.

| Recovered idle/compute statistic | Value |
|---|---:|
| FOC wall max | 28.0647us |
| >50us deadline misses | 0 |
| Actual CCR commits | 11052147 |
| Actual CCR late | 0 |
| Actual margin minimum | 16.6294us |
| CUR_CONFIRM enter / clear / fault | 4392 / 4392 / 0 |

These timing maxima belong to the recovered no-START startup/idle run, not a
new motor-on speed test. Current-invalid remains an independent blocking fault.

## Recovery and final physical state

When the lost session was detected, the host explicitly disabled SD/MOE/CCER,
halted the MCU, and captured full Flash and RAM without reset/resume/START.
The first follow-up RAM command failed; a subsequent halt/read-only capture
succeeded. The later attach showed the application had advanced while debugger
ownership was changing. The preserved first-fault snapshot remained valid;
no claim is made of cycle-simultaneity between the Flash and RAM reads.

After the user confirmed drive12V OFF, the existing bootloader
SET_CONFIRMED_SLOT mailbox restored the unchanged original B image. No flash
programming, direct metadata write, forced application health confirmation,
fault clear, algorithm or protection edit was performed.

Final readback: confirmedB, pendingnone, attempts0, generation645. CPU halted
at B Reset_Handler before B application instructions; SD=0, BDTR=0, CCER=0.
All application/private bytes were verified unchanged through selection. The
new A remains in Flash but is not the selected startup application.

## Evidence

- `tmp/sb1-speed-inspect-1792305899940048200.json`
- `tmp/sb1-speed-interrupted-final-flash.bin`
- `tmp/sb1-speed-interrupted-final-ram.bin`
- `tmp/sb1-speed-interrupted-final.json`
- `tmp/sb1-speed-interrupted-restore-1792309780887185200.json`
- `tmp/sb1-speed-interrupted-restore-1792309780887185200-flash.bin`

The SB1 kernel's6 offline tests and the acceptance runner's7 no-device tests
passed before the attempt. They do not replace the missing live speed test.
The runner currently keeps its final receipt in memory until exit: an abrupt
host interruption can lose it. A follow-up should add durable phase/START
logging before another authorized motor test; never infer completion from the
absence of a final receipt. The host's2s STOP deadline also cannot be asserted
as executed when its process is lost; the unchanged board lease is12s.

Next work: address test-runner evidence durability and distinguish the idle
CURRENT_INVALID sample window before a fresh protected speed acceptance. No
such retry or controller change was performed here.
