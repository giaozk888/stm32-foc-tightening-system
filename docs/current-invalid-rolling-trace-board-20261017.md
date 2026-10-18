# CURRENT_INVALID rolling trace — board acquisition 2026-10-17

## Outcome

One bounded, no-START diagnostic trial completed. The 30-second observation
period did **not** reproduce CURRENT_INVALID. Acquisition remains incomplete:
`CURRENT_INVALID_NOT_REPRODUCED`, not a captured-fault or root-cause PASS.
No control algorithms, protection settings or firmware were changed in this run.

## Exact evidence

- Image: `foc2_app_a/build/CurrentInvalidRollingTrace/foc2.bin`
- BIN SHA256: `47dfff9f3d3e80aea5c2621ae30fb8e94df2ee25a1fc4e8193f497522dc7a3d7`
- ELF SHA256: `d5370c056e93de8c67cbb11b3a6aa873004aba00be829df15d8c851f6a78670a`
- Stage receipt: `safety_backups/protected-closed-loop-20261014/current-invalid-rolling-trace-stage-1792242905530404100.json`
- Trial receipt: `safety_backups/protected-closed-loop-20261014/current-invalid-rolling-trace-trial-1792243028066757100.json`
- Full Flash and RAM remain in the private directory specified by that receipt.
- Auto-confirmation completed normally, A selected at metadata generation 626.
- Image is HARD_OFF=0; the existing READY computation path kept SD/MOE/CCER
  disabled. This was not an electrically active bridge or motor acceptance.
- Host motor commands = 0. No retry, forced confirmation or threshold edits.
- All application/private Flash bytes matched their staged values after trial.

## Measured results

| Metric | Observed |
|---|---:|
| FOC wall maximum, including diagnostic overhead | 30.88235 us |
| Deadline misses >50 us | 0 |
| Actual CCR commits | 632848 |
| Actual CCR late commits | 0 |
| Minimum actual CCR margin | 2024 ticks = 11.90588 us |
| CUR_CONFIRM entry / clear / fault | 239 / 239 / 0 |
| CUR_CONFIRM maximum cycles / elapsed | 2 / 101 us |
| Final fault snapshot valid | 0 |
| CTR2 frozen / freeze reason | 0 / 0 |
| Final 16 trace sequences | 656833–656848 |

The ring continued rolling past recovered CUR_CONFIRM events. It did not freeze
prematurely. The final 16 frames are a stopped-session tail, not a fault window;
they must not be presented as the missing three-unresolved failure evidence.
The ANALOG SAFE shutdown precedes the halted RAM capture, so this unfrozen tail
also must not be used as a proof of PWM generation during the earlier run.
Heavy preemption profiling was disabled; no IRQ attribution result is claimed.

## End state / next action

SD/MOE/PWM are off and MCU halted in A. B fallback image is unchanged but B boot
selection has **not** yet been restored at this report's creation. Await physical
12 V OFF confirmation before the existing bootloader B-selection restore.
Do not restart automatically. A new, explicitly bounded longer acquisition may
be considered separately; no fault threshold should be changed to induce a hit.
