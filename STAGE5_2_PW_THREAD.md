# Stage 5.2 — `pw_thread` FreeRTOS backend

## Scope

This stage adds Pigweed thread creation and yield support on the existing
FreeRTOS V11.3.1 kernel. Existing native FreeRTOS tasks, FOC/ADC ISRs, Router,
Protocol, BootHealth, IAP, and flash layout are unchanged.

`pw_thread::sleep_for` is intentionally deferred because it introduces the
`pw_chrono` facade and clock backend. The smoke worker uses `pw_thread` for
thread creation and yield, and the already validated native `vTaskDelay()` for
its short timing check.

## Allocation policy

The Pigweed smoke thread uses:

```text
pw::thread::freertos::StaticContextWithStack<256>
```

This provides a static 256-word (1024-byte) stack and static FreeRTOS TCB.
Pigweed dynamic thread-context allocation is disabled with:

```text
PW_THREAD_FREERTOS_CONFIG_DYNAMIC_ALLOCATION_ENABLED=0
```

FreeRTOS static allocation APIs are enabled alongside the existing dynamic
allocation APIs. `configKERNEL_PROVIDED_STATIC_MEMORY=1` lets the kernel own
the idle-task static buffers. Existing application tasks still use their
previous allocation method.

## Smoke-test lifecycle

After UART async runtime enable:

1. `PW_ThreadSmokeStart()` creates a priority-1 Pigweed thread named
   `PwSmoke`.
2. The `pw::Thread` handle is explicitly detached.
3. The worker logs its start.
4. It calls `pw::this_thread::yield()`.
5. It delays for 25 ms using FreeRTOS and logs completion.
6. Returning from the worker enters Pigweed's FreeRTOS cleanup path and the
   task deletes itself.

Expected output:

```text
[PW][INF][PWTHREAD] created static_stack=256 words priority=1
[PW][INF][PWTHREAD] worker start backend=FreeRTOS
[PW][INF][PWTHREAD] worker complete yield=OK delay=25ms
```

## Build result

Clean builds completed for both slots:

```text
APP A: FLASH=143372 B (62.51%), RAM=49512 B (37.79%)
APP B: FLASH=143056 B (62.37%), RAM=49496 B (37.78%)
```

Compared with Stage 5.1, Stage 5.2 adds approximately 5.7 KiB of flash and
1.7 KiB of static RAM. The RAM increase includes the 1024-byte smoke-thread
stack plus its TCB, context, and the FreeRTOS static-idle-task storage.

## Board validation — 2026-09-23

Both slots were updated through the existing UART A/B IAP flow and passed the
five-second BootHealth gate.

APP A produced all three `PWTHREAD` lines, remained at approximately 20 kHz
ADC/FOC execution, and committed with no pending trial. APP B then passed the
same checks.

Final state:

```text
CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=113
APP SLOT: B @ 0x08040000
[PW][INF][PWTHREAD] created static_stack=256 words priority=1
[PW][INF][PWTHREAD] worker start backend=FreeRTOS
[PW][INF][PWTHREAD] worker complete yield=OK delay=25ms
ADC/s=20000 FOC/s=20000 FLT=0
```

## Files

- `foc2_app_a/Middleware/pigweed/pw_thread_smoke_test.cc`
- `foc2_app_b/Middleware/pigweed/pw_thread_smoke_test.cc`
- both APP `CMakeLists.txt` files
- both APP `Core/Inc/FreeRTOSConfig.h` files
