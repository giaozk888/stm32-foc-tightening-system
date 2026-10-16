# Stage 5.9.2 - Pigweed tokenized log strings

## Goal

Add opt-in `pw_log_tokenized` records without replacing the readable Stage
5.9.1 text log path. This keeps bring-up and fault diagnosis readable while
allowing repetitive/high-rate logs to transmit a token plus compact arguments.

## Data path

```text
compile-time format string
  -> Pigweed token + varint arguments
  -> prefixed Base64 ($...)
  -> Stage 5.9.1 bounded queue/history
  -> UART DMA

ELF .pw_tokenizer.entries
  -> host Pigweed detokenizer
  -> original message/module/file fields
```

The token dictionary is retained in the ELF as an INFO section and is excluded
from the flashable BIN/HEX image. The MCU therefore does not store the original
tokenized format string in Flash.

## Compatibility and safety

- Existing `PW_LOG_*`, `LOG STATUS`, `LOG DUMP`, filtering, drop accounting,
  FOC, Router, RPC, KVS, transfer, and IAP behavior are unchanged.
- Tokenized records use the same nonblocking 24-record queue and 16-record
  history as text logs.
- Calls from ISR context remain forbidden.
- Text output uses `[PWT] ... $Base64`; it remains safe on the existing ASCII
  UART transport and can be decoded using the matching ELF.

## Commands

```text
4100 LOG CLEAR
4101 LOG TOKEN TEST 3
4102 LOG STATUS
```

`LOG STATUS` adds:

- `TOK`: accepted tokenized records;
- `TBIN`: total compact binary token/argument bytes;
- `TB64`: total prefixed Base64 bytes transmitted inside the record.

## Test

```powershell
.\tools\log_tokenized_smoke.ps1 `
  -Port COM5 `
  -Elf .\foc2_app_a\build\Debug\foc2.elf
```

The test captures three target records, decodes one through Pigweed's host
detokenizer using the matching ELF, verifies its arguments, and checks that
motor control remains IDLE and fault-free.
