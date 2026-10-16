# Stage 5.8 - Official pw_transfer Write stream

> Historical record, superseded on 2026-10-07. This stage used the official RPC
> identity with a project-owned Chunk state machine; it was not the full upstream
> transfer engine. Its hardware results below apply only to that historical build.
> The new local UART path uses actual upstream `TransferService`, `Thread`, and
> `Client::Write`; see [the current implementation and verification](firmware_common/UART_OFFICIAL_FIRMWARE_TRANSFER_20261007.md).
> `transfer_iap_stream.ps1` now requires `-AllowUpgrade` and stages by default;
> `-AllowReset` is additionally required to send `FW END`. The old RAM stream
> smoke script expects `STREAM=1` and is not compatible with the new engine entry.

## Result

The firmware now exposes the official Pigweed RPC identity:

```text
service: pw.transfer.Transfer  ID=0x5BD6C87B
method : Write                 ID=0xD4630586
type   : bidirectional streaming
```

The existing `foc.Transfer/Exchange` unary method remains registered as a
recovery-compatible fallback. Both transports call one shared Chunk V2 state
machine, so offset checking, retransmission, resource selection, flash writes,
and completion behavior cannot diverge.

## RPC sequence

The streaming transport uses one call ID for the whole transfer:

1. `REQUEST` opens `pw.transfer.Transfer/Write`.
2. `CLIENT_STREAM` carries START, START_ACK_CONFIRMATION, and DATA chunks.
3. The target replies with `SERVER_STREAM` chunks.
4. `CLIENT_REQUEST_COMPLETION` closes the stream.
5. The target replies with the final `RESPONSE`.

The server enables `PW_RPC_COMPLETION_REQUEST_CALLBACK=1`, so the final client
completion request is acknowledged instead of leaving the call open.

## A/B firmware integration

Resource 2 continues to use the existing bootloader-owned IAP transaction:

```text
FW BEGIN -> official Write stream -> FW END -> reset -> trial -> auto-confirm
```

No Flash address, A/B slot size, metadata layout, mailbox address, DBANK, or
BFB2 setting was changed.

## Real hardware validation

- RAM stream: 62 bytes, deliberate bad offset, retransmit recovery 1, CRC32
  `0x918BD039`.
- Full APP A stream: 201144 bytes, 6286 data chunks, retransmit 0, image CRC32
  `0x51872F72`.
- Boot result: `CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0`.
- Legacy unary transfer smoke test still passes.
- Allocator, KVS, RPC, UART, and motor-control regression checks pass.

## Commands

RAM/retransmit smoke test:

```powershell
.\tools\transfer_stream_smoke.ps1 -Port COM5
```

Full inactive-slot firmware upgrade:

```powershell
.\tools\transfer_iap_stream.ps1 -Port COM5 `
  -Image .\foc2_app_b\build\Debug\foc2.bin
```
