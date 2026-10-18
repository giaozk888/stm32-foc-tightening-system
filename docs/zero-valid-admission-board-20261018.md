# Zero valid-sample admission: repeated board calibration, 2026-10-18

Result: PASS for two real startup zero calibrations. No START was sent; no
motor operation or new speed-loop acceptance is claimed.

## Scope and image

The user confirmed drive 12 V OFF before programming, then normal drive supply
ON with motor U/V/W disconnected for the calibration run, and OFF again before
restoring the original B boot selection. IU/IV and MCU supply were unchanged.
The physical limit remained the previously requested 12 V / 0.5 A.

Only inactive A was programmed, using ZeroValidAdmissionTrial (228428 bytes),
SHA256 `11b99efb2323f552b568bb3e8dcbf2f1e0cab5257bd81f15816be2fad475e7e6`.
All 512 KiB were read back. Image, erased-page tail, unchanged B, bootloader,
configuration and metadata were checked against the recovered B637 baseline.
No control algorithm, protection threshold or firmware source was changed
during this board-verification step. Only the new no-motion runner and its
offline guard tests were added.

## Actual zero results

The existing bootloader START_TRIAL operation was submitted once. Normal
five-second health confirmation succeeded and requested its usual reset.
This produced two independent startup calibrations, not an automatic retry
after a failed calibration.

| Startup | Valid pairs | Rejected pairs | Physical collection pairs | Reject rate | Max consecutive rejected | Zero U / V |
|---|---:|---:|---:|---:|---:|---|
| Trial A startup | 4000 | 49 | 4050 | 1.21% | 1 | 1559 / 1563 |
| Confirmed A after health reset | 4000 | 39 | 4040 | 0.97% | 1 | 1560 / 1563 |

Both results: READY state=3, reason=0, flags=0, result=1. Both had one buffered
unused tail pair, consistent with the five-pair median admission design.
Rejects were below 80, consecutive rejects below three, and collection below
4100. U differed by one ADC count and V was unchanged between the two runs.

This demonstrates that real rejected samples no longer prevent collecting
4000 valid pairs under these two startup conditions. The historical exact
two-outlier block was covered offline; these two board captures reported a
maximum consecutive rejection of one and do not establish which five-pair
blocks contained multiple nonconsecutive rejects.

## State and recovery

Before stopping, the read-only status reported READY, USED=0, FLAGS=0,
FAULT=0, SD=0, MOE=0, CCER=0; mode was not commanded to run. Normal A health
confirmation reached metadata generation640. The host then disabled outputs,
halted the CPU and captured Flash. All application/private bytes were unchanged
by the trial; only normal boot metadata updates occurred.

After the user confirmed 12 V OFF, the existing bootloader SET_CONFIRMED_SLOT
mailbox restored original B. The CPU stopped at B Reset_Handler before any B
application instruction executed. Final metadata: confirmed B, pending none,
attempts0, generation641. Final readback proves SD=0, MOE/BDTR=0, CCER=0,
CPU halted, and all application/private bytes unchanged during selection.
The tested A image remains staged, but B is selected to boot.

No motor START, fault clear, forced application health confirmation, direct
Flash metadata programming or protection bypass was used. FOC timing was not
requalified by this narrow zero-calibration test; speed control and loaded
tightening still require their own acceptance.

## Local evidence and test runner

- `tmp/zero-valid-admission-stage-1792305316660538600.json`
- `tmp/zero-valid-admission-trial-1792305374490452200.json`
- `tmp/zero-valid-admission-restore-1792305501397657400.json`
- `tools/zero_valid_admission_board_test.py`
- `tests/test_zero_valid_admission_board_test.py`: 6 no-device guard/parser/scope
  tests PASS; default invocation cannot open hardware, power gates precede file
  or device access, changed images/scopes/reports are rejected.

The existing 12 zero-admission offline tests were re-run successfully before
board programming. Full historical suite limitations remain as recorded in
`zero-valid-sample-admission-20261018.md`; this narrow board result does not
turn those historical checks into passing tests.
