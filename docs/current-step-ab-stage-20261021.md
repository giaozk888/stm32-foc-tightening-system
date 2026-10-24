# Current-loop step A/B — staged, NOT activated

User confirmed: shaft mechanically locked, driver 12V OFF, MCU powered,
motor/fixture/shielding and wiring unchanged, supply 12V/0.5A and operator can
cut power immediately. No current injection or normal START was sent.

- Runner: `tools/current_step_ab_board.py`; default invocation is files-only.
- Host transport tests: `tests/test_current_step_ab_board.py`, 5 PASS.
- Stage receipt: `tmp/current-step-ab-stage-1792570318498727300.json`, PASS.
- Image: A `CurrentStepAbDiagnostic`, 214300 bytes.
- BIN SHA256: `d7b3dd465a113d1f7efcec85fcd472bd8706dbb34566317c5f4ef6b82c2ec9eb`.
- ELF SHA256: `ab126352bac51fb121f3c00319e0771f19ce224484763ca2e125bd93c1dd2a9e`.
- Full pre-write Flash matched the previously stopped B888 baseline before
  erase. Only inactive-A pages were programmed. Full Flash readback validated
  the image and all outside-page bytes; independent full readback matched.
- Original B, bootloader, metadata and private configuration unchanged.
- B remains selected, no pending trial. A has NOT been activated.
- SD=0, MOE/AOE=0, CCER=0, MCU halted. No motor commands, no current injected.

Next requires fresh driver-ON/no-alarm confirmation while the locked fixture,
shielding, wiring and 0.5A supply limit remain unchanged and the operator is
present. Then only one normal A/B trial request, calibration/timing/health
preflight, and (if preflight passes) one firmware-owned step batch are allowed.
Any protection/unknown command outcome stops with no retry. The negative
segments remain conditional on the six positive response quality checks.

Do not run the historical FSM runner or send normal START with this image.
Do not automatically restore/activate anything while the power state is
unknown; original B restoration is a separate drive-OFF phase after evidence
is captured and outputs are independently verified off.
