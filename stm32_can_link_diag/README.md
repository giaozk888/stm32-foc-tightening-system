# STM32 CAN SRAM diagnostic

This temporary image is linked entirely into STM32G474 SRAM at `0x20000000`.
It does not overwrite the bootloader or A/B application flash. It supersedes
the currently bus-off A-slot CAN probe for a clean, bounded physical-link test.

- Keeps PC6 (`CTRL_SD`) low; never initializes PWM, ADC, FOC, or motor tasks.
- Uses COM5/LPUART1 at 115200 8N1 for diagnostics.
- Uses PB9/PB8 FDCAN1 in classic CAN normal mode, 500 kbit/s. It detects
  whether the inherited PCLK1 is 170 MHz or 16 MHz and selects the matching
  timing; any other clock is rejected before CAN starts.
- Sends at most ten standard-ID `0x701` frames, one per second, with automatic
  retransmission disabled; then stops FDCAN and holds PC6 low.
- Reports TXBTO, TEC/REC, bus-off, last error and any received frames on COM5.

Build with the sibling project's toolchain file:

```powershell
cmake -S 'D:\new project\stm32_can_link_diag' -B 'D:\new project\stm32_can_link_diag\build_ram' -G Ninja -DCMAKE_TOOLCHAIN_FILE='D:\new project\stm32_esp_link_diag\toolchain.cmake' -DCMAKE_BUILD_TYPE=Release
cmake --build 'D:\new project\stm32_can_link_diag\build_ram'
```

The ELF has one load segment at `0x20000000`; it must only be loaded into RAM
with a debugger, not flashed. Loading/running it interrupts the current APP.
Before doing so, confirm PD6010B input and CTRL_SD are both 0 V and keep the
motor power stage off. A-slot metadata currently has zero trial attempts, so
an MCU reset would roll back to confirmed B; do not reset merely to recover CAN.
If the previous application is running, halt it and set PRIMASK=1 through the
debugger before pointing PC/VTOR at this SRAM image. Otherwise an already
pending ADC interrupt can enter the diagnostic's default handler before main()
has a chance to disable and clear inherited NVIC state. Verify TIM1 MOE=0 and
PC6/CTRL_SD=0 before resuming the SRAM image.

Expected link proof: LubanCat `candump -L can0` shows ID `701` while the SRAM
probe reports a successful TX indication and low TEC. A local Linux loopback
frame alone is not proof of the external two-node link.

For the reverse-direction test, configure a separate `build_ram_rx` directory
with `-DCAN_RX_ONLY=ON`. That image only listens on PB8 for 30 seconds, prints
the received ID and first four data bytes on COM5, then stops FDCAN. It retains
the same SRAM-only and power-stage-off safety behavior.

For HMI framing diagnostics, build with `-DCAN_STATUS_V1_PROBE=ON` in a
separate `build_status_v1` directory. This mode is mutually exclusive with
`CAN_RX_ONLY`; it attempts at most 50 classic CAN `0x180` frames with the
status-v1 byte layout and a reserved diagnostic fault marker `0xFFFE`, then
stops FDCAN. It does not mean that the normal APP has started. It uses a
SysTick COUNTFLAG polling delay because a debugger-launched SRAM image can
inherit an unserviced SysTick interrupt. Keep a second node listening with
`candump -L can0,180:7FF` and require both a received frame and a successful
STM32 transmit indication before calling the link proven.

On 2026-09-28, one initial run enqueued frames but had `TXBTO=0`, rising
TEC (8 to 128), and no LubanCat frames. The user reported unchanged wiring.
After adding a reset of the inherited LPUART state and using COUNTFLAG polling
in both transmit variants, a bounded same-wiring retest produced actual
`0x701` frames on LubanCat (`seq=1..9`, STM32 TEC=0 and TXBTO nonzero),
followed by actual `0x180` status-format frames (`seq=28..38` with one gap;
STM32 TEC was 2 at seq40). Both probes stopped FDCAN and left PC6 low/TIM1
MOE clear. The transient initial failure is not explained and must not be
attributed to rewiring. No normal APP Flash or boot metadata was written.
