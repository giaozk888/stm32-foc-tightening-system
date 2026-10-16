# Stage 5.9.1 - Buffered pw_log backend

## Architecture

`PW_LOG_*` calls format into a bounded record and perform a zero-wait enqueue
to a static FreeRTOS queue. A priority-1 `PwLog` task forwards records to the
existing UART DMA ring. Motor control, Router, RPC, and protocol replies never
wait for log output.

```text
PW_LOG -> static queue (24 records) -> PwLog task -> UART 8 KiB ring -> DMA
             |
             +-> history ring (last 16 records)
```

The queue, history, and task stack are all statically allocated. The feature
does not consume the FreeRTOS dynamic heap or `pw_allocator`.

## Safety policy

- Calls below the runtime level are counted as `FILTERED`.
- A full queue increments `DROP_FULL`; it never blocks the caller.
- A UART enqueue failure increments `DROP_UART`.
- Calls from interrupt context are rejected and counted as `DROP_ISR`.
- No logging is performed from the 20 kHz ADC/FOC ISR.

## Commands

```text
4000 LOG STATUS
4001 LOG DUMP
4002 LOG CLEAR
4003 LOG LEVEL DEBUG|INFO|WARN|ERROR|CRITICAL|FATAL
4004 LOG TEST 64
```

`LOG STATUS` reports queue depth/capacity, history count, sequence number,
enqueue/send/drop/filter counters, and queue high-water mark. `LOG DUMP` emits
the last 16 retained records in chronological order.

## Test

```powershell
.\tools\log_smoke.ps1 -Port COM5
```

The test verifies level filtering, a 64-record burst filling the 24-record
queue without blocking, nonzero drop accounting, 16-record history dump,
counter clearing, and an IDLE/fault-free motor-control regression status.
