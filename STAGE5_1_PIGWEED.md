# Stage 5.1 — Pigweed `pw_log` / `pw_assert`

## Scope

This stage adds only:

- Pigweed C++17 build support;
- `pw_log` through the `pw_log_string` frontend;
- `PW_CHECK` and `PW_DCHECK` through the `pw_assert_log` check backend;
- one startup smoke test in both APP A and APP B.

It does not add `pw_thread`, `pw_unit_test`, `pw_kvs`, `pw_rpc`,
`pw_transfer`, or `pw_allocator`. FOC, Router, IAP layout, metadata, and the
FreeRTOS task design are unchanged.

## Source pin

Pigweed is stored in `third_party/pigweed` and pinned in
`third_party/PIGWEED_REVISION.md`.

Only the Stage 5.1 source/header subset is built. The Pigweed root CMake project
is deliberately not added because it configures unrelated modules and tests;
those modules will be introduced one stage at a time.

## Runtime path

```text
PW_LOG_INFO / PW_CHECK failure
        -> pw_log_string
        -> pw_log_string_HandleMessageVaList
        -> UART_Async_Write (best effort, non-blocking)
        -> existing 8 KiB TX ring
        -> existing DMA1 Channel 1
        -> LPUART1
        -> PC
```

Router/IAP replies continue to use `UART_Async_WriteReliable()` and are not
rerouted through Pigweed.

## Project files

Both `foc2_app_a` and `foc2_app_b` contain:

- `Middleware/pigweed/pw_log_backend.c` — STM32 UART backend;
- `Middleware/pigweed/pw_smoke_test.cc` — startup log/assert smoke test;
- a `PW_SmokeTest()` call immediately after async UART runtime enable.

The smoke test uses passing conditions only:

```cpp
PW_LOG_INFO("Pigweed alive");
PW_CHECK(x == 123);
PW_DCHECK(ptr != nullptr);
```

## Build

Run separately in each APP directory:

```powershell
cmake --preset Debug
cmake --build --preset Debug --clean-first -j 8
arm-none-eabi-objcopy -O binary build\Debug\foc2.elf build\Debug\foc2.bin
```

Expected startup output after installing the corresponding slot image:

```text
[PW][INF][STAGE5] Pigweed alive
[PW][INF][STAGE5] MCU=STM32G474 SLOT=A
[PW][INF][STAGE5] pw_assert checks passed
```

APP B prints `SLOT=B`.

Absence of the last line indicates that startup did not pass both checks.

## Board validation — 2026-09-23

Validated on the connected NUCLEO-G474RE through COM5 at 115200 baud.

1. Started from confirmed APP B.
2. Updated inactive APP A through the existing UART IAP protocol.
3. APP A completed the trial health gate and committed:
   `CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0`.
4. APP A printed all three Stage 5.1 smoke-test lines.
5. Updated inactive APP B through the same IAP path.
6. APP B completed the trial health gate and committed:
   `CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0`.
7. APP B printed all three Stage 5.1 smoke-test lines.

The final observed application status was:

```text
APP SLOT: B @ 0x08040000
[PW][INF][STAGE5] Pigweed alive
[PW][INF][STAGE5] MCU=STM32G474 SLOT=B
[PW][INF][STAGE5] pw_assert checks passed
BOOT HEALTH: current slot is already confirmed; auto-confirm task idle
ADC/s=20001 FOC/s=20001 FLT=0
```

Final metadata generation after confirming B was 107. The power/control loop
remained operational and the device stayed in IDLE throughout the update test.
