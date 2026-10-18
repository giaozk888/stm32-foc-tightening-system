# Current-feedback polarity hard-OFF board comparison (2026-10-18)

## Scope and safety

User confirmed drive 12 V OFF, MCU powered and U/V/W power leads disconnected
before programming. The reverse-sign B image was compiled with
`FOC_CURRENT_FEEDBACK_SIGN=1` and `FOC_FAST_REJECT_COMPUTE_ONLY=1`. The image
contains `HARD_OFF=1`; its ELF has no `PowerStage_Enable` symbol. User then
reported drive 12 V ON at 0.5 A and no driver alarm. No START or motion command
was sent. User turned 12 V OFF before restoration.

Preflight full Flash was 512 KiB, SHA256
`f7562227e89f3124341834e796af9a17a9cd4b3b38e03bfb0514046f062b0f32`.
Metadata was confirmed A, no pending trial, generation 626. The confirmed A
CRC matched its metadata. B image SHA256 was
`1414d15686290feded880fea9cba30b62c8e3772585ac452dba9905ce4dfaff9`
(225100 bytes). B was programmed and completely read back; every byte outside
the B erase-page range stayed the same, including A, bootloader, parameters,
private data and metadata. The first in-command `verify_image` encountered a
target-not-halted error; this is **not** counted as a pass. Subsequent full
readback comparison and a separate halted B `verify_image` passed.

## One trial and observations

The bootloader accepted one B trial. B later normally confirmed at generation
630. A startup `PROTECTED MOTOR ZERO FAILED` line appeared before the later
health-confirmation log; the retained serial transcript cannot unambiguously
assign that line to a particular boot. The final confirmed B run was READY with
zero calibration state 3/reason 0, no runtime fault, SD=0, MOE=0 and CCER=0.
No automatic second trial was submitted by the host.

The 10-second observation advanced ADC pairs from 44,079 to 249,328. The
latest zero was U=1564, V=1561 counts. Halted SRAM retained a final frame
with raw U=1571, V=1563, and computed IU=+0.04700855 A,
IV=+0.01343101 A, IW=-0.06043956 A. Those values exactly match
`(raw-zero)*3300/(4095*120)` and prove the reverse-sign conversion actually
executed on the MCU. They do **not** prove the physical motor-current polarity:
the disconnected motor had no controlled phase-current stimulus.

Post-test wiring clarification from the user (2026-10-18): the present
connection is driver IV -> MCU PA0 and driver IU -> MCU PA1, opposite to the
firmware's IU -> PA0 / IV -> PA1 assignment. It is not independently known
whether this wiring was identical during the captured trial. Consequently the
trial's raw U/V labels must not be treated as proof of physical phase mapping
or as a qualification of either control-feedback sign. Restore or explicitly
remap the two ADC channels before an actuating closed-loop test.

The last status query showed FOC work max 18 us, work late 0, ADC `MISS=0` and
ADC max 4728 cycles (27.81 us at 170 MHz). Periodic log reported FOC wall max
28.888 us, deadline miss 0, actual CCR late 0 and minimum actual margin
16.905 us. ADC `LATE=2` and ADC COMMIT `BOTTOM_LATE=2` are two names for the
same `deadline_misses` counter, not four independent events. The counter is a
conservative IRQ entry-to-exit versus remaining TIM1-bottom-ticks alarm,
distinct from actual CCR late; do not call the timing acceptance fully clean.
The one-shot script originally labeled
its narrower safety gate PASS; its future gate was tightened to reject those
warnings. There was no repeat trial.

The final `ANALOG SAFE` ACK reported SD=0/MOE=0/FOC=0. The MCU was halted and
Flash captured. Host motor-command count was zero. The user then confirmed
12 V OFF. The existing bootloader's `SET_CONFIRMED_SLOT` command restored A
and halted exactly at A reset entry `0x080192a0` before application code. Final
metadata: confirmed A, no pending trial, generation 631. Full readback verified
all application and private Flash outside metadata unchanged; SD=0, MOE=0,
CCER=0. The diagnostic B image remains in the inactive slot, but is not the
selected boot image.

## Offline checks and conclusion

Rebuilding the A/B reverse hard-OFF configurations found no work to do. All
28 relevant host tests passed. This run proves the compiled polarity switch is
effective and that a hard-OFF computation trial can reach a healthy final state.
It does not qualify the sign for closed-loop motor operation or resolve the
previous overspeed. The transient startup zero-failure line and two ADC/bottom
timing warnings warrant review before any powered motor test. A controlled
physical current-direction/phase-mapping measurement remains necessary.

Ignored local evidence (contains full Flash/RAM; do not publish):
`tmp/current-polarity-hardoff-trial-20261018.json`,
`tmp/current-polarity-staged-20261018.bin`,
`tmp/current-polarity-final-20261018.bin`, and
`tmp/current-polarity-restored-a-20261018.bin`.
