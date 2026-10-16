# Stage 5.9.3 - Multi-device log subscriptions over Router

## Architecture

Remote Router nodes subscribe to a logger node with a minimum severity and a
bounded lifetime. The existing `PwLog` task performs only a zero-wait copy into
a static mirror queue. `ProtocolTask` drains that queue and sends best-effort
Router packet type 6 records to each matching subscriber.

```text
PW_LOG / tokenized log
  -> Stage 5.9.1 log queue -> local UART DMA
  -> static mirror queue (8)
       -> ProtocolTask
          -> Router type 6 -> subscriber node(s)
```

This separation prevents the low-priority log task from concurrently touching
the Router route table. It also prevents a missing or slow remote listener from
blocking FOC, Protocol, or local logging.

## Limits and policy

- Up to four subscribers.
- Subscription lifetime: 1 to 3600 seconds; automatic expiry prevents stale
  routes from receiving logs forever.
- Per-subscriber minimum level filtering.
- Eight-record static mirror queue; full queues increment `DROP` and never
  block the producer.
- Log transport is deliberately best effort. Critical business events continue
  to use the existing reliable EVENT/EID/ACK path instead.
- Both text `[PW]` and compressed `[PWT]` records can be mirrored.
- UART1 Router output is prefixed with a CR/LF boundary because this project
  intentionally shares the port with legacy human-readable diagnostics. This
  prevents an unterminated diagnostic from absorbing a following `@R1` frame.

## Commands

A routed node subscribes itself:

```text
<REQ> LOG SUBSCRIBE INFO 30
<REQ> LOG UNSUBSCRIBE
```

A local administrator can select a node explicitly:

```text
<REQ> LOG SUBSCRIBE 2 WARN 60
<REQ> LOG UNSUBSCRIBE 2
```

Diagnostics:

```text
<REQ> LOG ROUTER STATUS
<REQ> LOG SUBSCRIBERS
```

## Test

The test emulates Router node 2 on the PC UART, sends a routed subscription,
checks two type-6 mirrored tokenized records, unsubscribes, verifies that the
next record is no longer mirrored, injects a type-6 record in the reverse
direction, and confirms motor control remains IDLE and fault-free.

```powershell
.\tools\log_router_smoke.ps1 -Port COM5
```
