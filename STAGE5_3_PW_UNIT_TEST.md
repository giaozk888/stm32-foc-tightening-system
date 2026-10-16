# Stage 5.3: pw_unit_test target integration

## Goal

Integrate Pigweed's lightweight unit-test backend without changing the FOC,
Router, IAP, BootHealth, or flash-layout behavior. Tests run once from
`StartupTask` after asynchronous UART is ready, then normal application tasks
continue.

## Integrated Pigweed modules

- `pw_unit_test` light backend
- `pw_unit_test::LoggingEventHandler`
- `pw_string` support required for expectation formatting
- Existing Stage 5.1 `pw_log` backend for UART DMA output

The default Pigweed test-object memory pool was reduced from 16 KiB to 2 KiB:

```cmake
PW_UNIT_TEST_CONFIG_MEMORY_POOL_SIZE=2048
```

This pool is static and does not consume the FreeRTOS heap.

## Initial target tests

Both APP A and APP B contain the same four RingBuffer tests:

1. Initial state and usable capacity.
2. Write/read behavior across physical-buffer wraparound.
3. Full-buffer behavior and rejection of an extra byte.
4. Contiguous peek and over-length consume clamping.

The entry point is `PW_UnitTestsRun()` in
`Middleware/pigweed/pw_unit_tests.cc`. It is called after the UART runtime gate
opens and before the Stage 5.2 thread smoke test starts. It is never called from
the 20 kHz ADC ISR or the 1 kHz motor-control task.

## Build and image generation

Both slots were clean-built with GCC ARM 15.3.1:

| Slot | Flash | RAM |
| --- | ---: | ---: |
| A | 167008 B / 224 KiB (72.81%) | 51720 B / 131008 B (39.48%) |
| B | 166688 B / 224 KiB (72.67%) | 51704 B / 131008 B (39.47%) |

A post-link CMake command now regenerates `foc2.hex` and `foc2.bin` after every
successful link. This prevents IAP from accidentally using an older binary
while the ELF is current.

## Hardware result

APP A and APP B were each transferred through the existing A/B IAP path,
trial-booted, and auto-confirmed by BootHealth. Both reported:

```text
[  PASSED  ] 4 test(s).
target unit tests complete result=0
```

After the final B-slot confirmation:

```text
CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=119
```

Runtime health after the tests remained normal:

```text
ADC/s=20001 FOC/s=20001 EN=1 FLT=0
```

## Adding another test

Add a new `TEST(SuiteName, CaseName)` block to `pw_unit_tests.cc`. Keep target
tests deterministic, short, and independent of live motor hardware. Hardware
integration tests belong in a separate command-driven test mode rather than in
the startup unit-test suite.
