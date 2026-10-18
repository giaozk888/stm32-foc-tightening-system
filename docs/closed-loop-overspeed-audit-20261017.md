# Closed-loop overspeed: saved-evidence audit (2026-10-17)

Read-only hardware diagnosis. No reset, motor start, Flash write, boot-selection
change, control-code change, parameter change or protection change was performed.
The last user-confirmed external 12 V state is OFF.

## Evidence and limits

Receipt: `safety_backups/protected-closed-loop-20261014/rolling-trace-closed-loop-motion-1792243725872504700.json`.
Its matching saved RAM was decoded with symbols from
`foc2_app_a/build/CurrentInvalidRollingTrace/foc2.elf` (receipt ELF SHA256
`d5370c056e93de8c67cbb11b3a6aa873004aba00be829df15d8c851f6a78670a`).
The startup trace has 40 outer-loop records in a 32-row ring; the retained
history starts at 8.890 ms after admission. It also has a separate first-fault
record at 39.896 ms, flags 1024 / CL_OVERSPEED. These rows are completed
outer-loop observations, NOT simultaneous ADC/encoder/voltage measurements;
in particular recorded Vd/Vq and currents can precede the row's new speed/Iq
command. Do not fit an exact plant transfer function from these rows.

## Established shutdown cause

The protected session's filtered-speed limit is 60 rpm. At fault its ramped
command was 7.9986 rpm (eventual requested target 20 rpm), measured filtered
speed 76.3627 rpm and instantaneous speed 435.7910 rpm. The loop was SPEED,
and the original tightening FSM was RUNDOWN; the position PI was not controlling
this startup. No CURRENT_INVALID or CUR_CONFIRM fault caused this stop.

FOC wall maximum was 31.92941 us, deadline misses 0, actual CCR late commits 0,
minimum actual margin 16.07647 us. One blocked commit keeps the receipt's
conservative `timing_pass=false`; it must not be relabelled a full timing PASS.
There is nevertheless no evidence here of a deadline/late-write shutdown.

## Startup evolution: current departure precedes the speed trip

Times are relative to protected-session admission, not the tightening state's
separate elapsed-ms field. Currents/voltages are software-estimated quantities.

| Time ms | Speed ref rpm | Filtered rpm | Iq ref A | Id A | Iq A | Vd V | Vq V |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 24.880 | 5.00 | 1.94 | 0.0102 | 0.048 | -0.004 | -0.020 | 0.025 |
| 28.878 | 5.80 | 1.46 | 0.0143 | 0.118 | -0.070 | -0.080 | 0.059 |
| 30.878 | 6.20 | 1.33 | 0.0161 | 0.257 | -0.089 | -0.152 | 0.094 |
| 32.877 | 6.60 | 2.05 | 0.0153 | 2.398 | -1.216 | -0.674 | 0.358 |
| 33.878 | 6.80 | 3.35 | 0.0121 | 3.799 | -2.059 | -0.703 | 0.382 |
| 34.879 | 7.00 | 7.73 | -0.0004 | 3.531 | -2.140 | -0.688 | 0.408 |
| 37.878 | 7.60 | 42.45 | -0.1057 | 0.957 | -2.017 | -0.447 | 0.663 |
| 39.883 | 8.00 | 76.36 | -0.2086 | -0.745 | -2.224 | -0.041 | 0.799 |

At low measured speed the nominal Id=0 axis is already diverging while Vd
becomes more negative; measured Iq becomes negative while Vq increases positive.
Later the speed PI requests braking, yet the feedback error remains large and
the voltage vector reaches its existing 0.8 V magnitude limit. This is a strong
reason to audit the current-feedback/phase-voltage polarity and phase mapping
before tuning the outer speed PI. It is NOT proof that simply negating both
current channels is the correct repair: phase swaps, driver-input polarity,
sampling errors and physical signal validity still require differentiation.

## Code and arithmetic checks

1. `LatestOriginal_Admit()` explicitly resets both current PI integrators and
   clears references/Vd/Vq before enabling the bridge. READY shadow-integrator
   carry-over is not an unhandled startup path in this image's source.
2. Speed PI error at fault is 7.9986 - 76.3627 = -68.3641 rpm. With Kp=0.003,
   P=-0.205092 A; the captured Iq reference -0.208564 A is consistent with a
   small integral contribution about -0.003472 A. The speed PI is commanding
   braking, not continuing a positive accelerating current request.
3. Current conversion in the active feedback path is
   `I=(zero-raw)*3300/(4095*120)` A, i.e. +6.71551 mA per downward ADC count.
   Whether this is the correct PHYSICAL sign is not established by a zero test.
4. Last ADC pair U=1271/V=1873, zero U=1563/V=1561 gives Iu=+1.960928 A,
   Iv=-2.095238 A. Clarke/Park at recorded angle 1.31323111 rad reproduces
   Id=-0.74526748 A and Iq=-2.22413503 A, agreeing with the fault snapshot.
   There is no arithmetic/sign mismatch between these recorded raw values and
   the reported dq currents. This does not validate their physical signs.
5. SVPWM duty uses `0.5 + phase_voltage/12`; the planner retains U/V/W order
   into CCR1/2/3. TIM1 CH1/2/3 are PWM1, active high; main outputs are
   PC0/PC1/PC2 and complementary outputs PB13/PB0/PB1. Source inspection did
   not find a software U/V/W permutation in this chain. Physical connections
   and the driver's input/output conventions cannot be proved from source.
6. Mechanical speed uses encoder delta * direction * 60 / (16384 * dt),
   with direction=-1; pole pairs=10 apply to electrical angle, not mechanical
   rpm. Last accepted raw angles 8550 -> 8431 over 1000 us independently give
   +435.791016 rpm. Thus no simple x10 pole-pair or fixed-dt unit mistake was
   found. Parity/status validity does not independently prove shaft speed.
7. Electrical angle uses the same configured direction=-1, 10 pole pairs and
   fixed zero_raw=10507. A successful SPI startup does not calibrate electrical
   zero. No conclusion that this offset remains physically correct is possible
   from the existing zero-current data alone.
8. Last 16 current frames are NORMAL/USE, unresolved-before=0, d_old<=22.
   Their currents evolve rather than being a final isolated rejected spike.
   Earlier holds/rejections exist, so this is not proof that all interference
   vanished or that sample validity is established over the whole startup.

## Conclusion / next discriminating check (not executed)

The immediate stop is proven overspeed. The earlier observable malfunction is
failure of measured dq current to track its small reference, before the speed
excursion. Prioritize current-sense sign and U/V phase correspondence relative
to actual applied phase voltage, then electrical-angle alignment and current
loop dynamics. The available evidence does not uniquely distinguish these
physical causes, nor justify changing PI gains, swapping phase wires, negating
currents or relaxing protection without a controlled polarity/mapping check.

The inline offline arithmetic checks (current reconstruction, speed-step
reconstruction, first-fault flags and final discriminator window) passed.
No firmware rebuild was needed: no firmware source was edited.
