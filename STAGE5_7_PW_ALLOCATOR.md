# Stage 5.7 - Pigweed pw_allocator

## Result

Both APP A and APP B now build Pigweed's `pw_allocator` core and the official
`FreeRtosAllocator` backend. The backend delegates to the project's existing
FreeRTOS `heap_4` implementation and its 32 KiB heap; it does not reserve a
second allocator arena.

## Runtime policy

Dynamic allocation is limited to task-context management and middleware code.
It is forbidden in interrupt context, the 20 kHz injected-ADC ISR, and the FOC
current-control path. `PW_Allocator_RunSelfTest` rejects calls made from an ISR
or before the scheduler is running.

## Validation

The bounded self-test performs two allocations through `pw::Allocator`:

1. a 96-byte, 8-byte-aligned raw allocation;
2. a typed `AllocatorProbe` constructed with `Allocator::New`.

It writes and verifies probe data, releases both objects, and requires the free
heap count after the test to equal the count before it. The same test is also
registered in `pw_unit_test` as `PwAllocator.FreeRtosHeapRoundTrip`.

## Serial commands

```text
3000 ALLOC STATUS
3001 ALLOC TEST
```

The reply reports:

```text
BACKEND=FREERTOS_HEAP4 FREE=<bytes> MIN=<bytes> PASS=<0|1>
ALLOCS=2 BEFORE=<bytes> LOW=<bytes> AFTER=<bytes> ISR=FORBIDDEN
```

`FREE` is the current FreeRTOS heap size and `MIN` is the minimum-ever free
heap size since boot. A passing round trip has `PASS=1` and `BEFORE=AFTER`.

## Files

- `foc2_app_a/Middleware/pigweed/pw_allocator_port.{h,cc}`
- `foc2_app_b/Middleware/pigweed/pw_allocator_port.{h,cc}`
- both `CMakeLists.txt` files
- both `Core/Src/main.c` files
- both `Middleware/pigweed/pw_unit_tests.cc` files
