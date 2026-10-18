# CTR2 A626 no-load closed-loop short test — 2026-10-17

## Result: not accepted

Exactly one original START was attempted and acknowledged as queued. At the
first host motion-status response, approximately 75 ms after START submission,
the controller had already latched a fault. No retry, firmware write, boot
selection change, protection edit, or persistent parameter save was performed.
User subsequently confirmed that the external drive 12 V supply was OFF.

Receipt: `safety_backups/protected-closed-loop-20261014/rolling-trace-closed-loop-motion-1792243725872504700.json`.
The same-session full Flash/RAM captures are private files referenced there.

The tested image is the exact CTR2 A used for the preceding output-disabled
test. It contains the existing protected original START/tightening path and the
one-cycle PWM pipeline; HARD_OFF=0. Its successful output-disabled test was not
treated as evidence of successful powered closed-loop regulation.

## First-fault evidence

| Item | Captured value |
|---|---:|
| Fault domain / protection reason | 2 / 3 (protection / HEALTH) |
| First protection flags | 1024 = 0x400 = CL_OVERSPEED |
| Existing filtered-speed trip threshold | 60 rpm |
| Command target for this test | 20 rpm |
| Ramped speed command at fault | 7.9986 rpm |
| Encoder-derived filtered speed at fault | 76.3627 rpm |
| Encoder-derived raw speed at fault | 435.7910 rpm |
| State elapsed at fault | 30 ms |
| Reported angle at fault | 10.76660 degrees |
| Encoder valid / errors | 1 / 0 |
| Iq reference / measured | -0.20856 A / -2.22414 A |
| Id measured | -0.74527 A |

Source mapping:
`protected_closed_loop.h`: CL_OVERSPEED=1024, CL_OVERSPEED_RPM=60.
`ProtectedLoop_HealthCaptured`: tests the magnitude of encoder_speed_rpm only
while CL_RUNNING. `ProtectedLoop_EmergencyOff` disables the outputs first,
captures the first flag, invalidates pending PWM and disarms the session.

The immediate shutdown condition is therefore proven to be the existing
overspeed guard, not CURRENT_INVALID, CUR_CONFIRM timeout or FOC deadline miss.
The external status REASON=9 is the generic protected-loop fault mapping;
the detailed first-fault flags establish the specific overspeed cause.

This proves what the firmware measured and why it stopped. It does not yet
prove whether the encoder-derived speed is physically accurate or explain the
underlying overshoot. Encoder CRC/parity error count 0 alone is insufficient to
validate scale, direction, electrical zero or the current/angle feedback chain.

## Timing and current discriminator

- FOC wall maximum: 5428 cycles / 170 MHz = 31.92941 us.
- >50 us deadline misses: 0.
- Actual CCR commits: 70102; late commits: 0.
- Minimum actual margin: 2733 ticks = 16.07647 us.
- Commit blocked: 1; post-unsafe writes: 0.
- CUR_CONFIRM: 27 entries / 27 clears / 0 faults; maximum 2 cycles, 100 us.
- Unresolved consecutive at fault: 0; maximum consecutive for this boot: 1.

The decoder conservatively sets timing_pass=false when ANY blocked commit is
present. Do not relabel it as a complete timing PASS. A blocked count is not
itself proof of late write: PipelineCommit first invokes the health predicate,
which can trip overspeed and revoke permission before the CCR stores. This is
consistent with the first overspeed snapshot; the light counter alone does not
separately encode which blocked branch was taken.

CTR2 retained the last 16 consecutive pairs, seq 94089–94104. They all took
NORMAL/USE with unresolved-before=0 and d_old<=22 counts. The ring was not
frozen because it freezes only on CURRENT_INVALID by design. These are not a
three-unresolved CURRENT_INVALID window and must not be described as such.

## Shutdown and unchanged state

The runner issued STOP, restored and read back all temporary recipe fields,
then verified ANALOG SAFE: LATCHED=1, SD=0, MOE=0, FOC=0. ST-Link subsequently
verified output-off registers and halted the MCU. Full Flash SHA256 remained
`f7562227e89f3124341834e796af9a17a9cd4b3b38e03bfb0514046f062b0f32`;
metadata generation remains 626, confirmed A, with no pending trial. B fallback
and private data are unchanged. No B boot-selection restore was performed.

The runner's STOP/IDLE warning means it could not observe filtered speed below
2 rpm: repeated fault-status replies retained 76.3 rpm and 10.76 degrees.
The disarmed task stops periodic encoder updates. These repeated values do NOT
prove the shaft continued rotating at that speed after shutdown; independent
off-register and safe-latch evidence above remains separate from speed telemetry.

## Next diagnostic direction (not executed)

Keep protection thresholds unchanged. Before another motor start, analyze the
startup encoder/current/voltage histories to distinguish a speed-estimation
artifact from incorrect current-loop direction/electrical-angle alignment or a
genuine startup transient. No tuning or wiring change is justified solely by
this single first-fault snapshot.
