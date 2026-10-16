# STM32G474 A/B IAP Trial/Rollback 修复说明

## 1. 项目结构

- Bootloader：`D:\new project\foc2_bootloader`
- APP A：`D:\new project\foc2_app_a`
- APP B：`D:\new project\foc2_app_b`
- UART 更新工具：`D:\new project\iap_update_v2_begin_recovery.py`

Flash 地址保持不变：

| 区域 | 地址 |
|---|---:|
| Bootloader | `0x08000000` |
| APP A | `0x08008000` |
| APP B | `0x08040000` |
| Metadata Copy1 | `0x0807E800` |
| Metadata Copy0 | `0x0807F000` |
| 参数区 | `0x0807F800` |

## 2. 原始故障

更新 APP A 后，Bootloader 状态出现：

```text
CURRENT=B
CONFIRMED=B
PENDING=A
ATTEMPTS=0 或 1
```

主要表现：

- A 固件接收及 CRC 校验成功；
- Bootloader 已尝试启动 A；
- 系统最终仍运行 B；
- trial 耗尽后曾出现 `pending=A, attempts=0` 未清理；
- APP A 启动后不会执行健康确认。

## 3. Bootloader 修改

修改文件：`D:\new project\foc2_bootloader\Core\Src\main.c`

### 3.1 Trial 次数提交

增加 `Boot_CommitTrialAttemptV3()`：

1. 跳入 pending APP 前先递减 `attempts_left`；
2. 写入 Metadata V3 双副本；
3. 重新读取并校验提交结果；
4. 提交失败时不进入 APP，防止状态失配。

### 3.2 Trial 耗尽回滚

增加 `Boot_CommitPendingClearV3()`，trial 耗尽时原子提交：

```text
pending_slot  = NONE
pending_size  = 0
pending_crc32 = 0
attempts_left = 0
confirmed_slot 保持不变
generation++
```

提交后重新读取 Metadata 进行验证，成功后才启动 confirmed APP。

### 3.3 启动轨迹

在原有 64 字节 SRAM mailbox 的后 32 字节增加 `BootTrace_t`，未改变 mailbox 基址和预留大小。

轨迹记录 Bootloader 启动次数、本次和上次跳转目标、复位标志以及 Metadata 状态。

无复位读取命令：

```powershell
& "D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe" `
  -c port=SWD mode=HOTPLUG freq=1000 `
  -r32 0x2001FFE0 32
```

必须使用 `HOTPLUG`，避免调试连接触发复位并消耗 trial 次数。

## 4. APP A 根因及修改

修改文件：`D:\new project\foc2_app_a\Core\Src\main.c`

最终确认的主要根因是：APP A 虽然链接到 `0x08008000`，但源码仍保留 APP B 的身份配置。

错误配置：

```c
#define APP_THIS_SLOT          (BOOT_SLOT_B)
#define APP_THIS_ADDRESS       (APP_B_ADDRESS)
#define APP_TARGET_SLOT        (BOOT_SLOT_A)
#define APP_TARGET_ADDRESS     (APP_A_ADDRESS)
```

这导致 Bootloader 已跳入 A，但程序仍自认为是 B，BootHealthTask 不执行 A 的自动确认，而且升级目标错误指向自身。

修正配置：

```c
#define APP_THIS_SLOT          (BOOT_SLOT_A)
#define APP_THIS_ADDRESS       (APP_A_ADDRESS)
#define APP_TARGET_SLOT        (BOOT_SLOT_B)
#define APP_TARGET_ADDRESS     (APP_B_ADDRESS)
#define APP_TARGET_END         (APP_B_END)
#define APP_TARGET_BANK        FLASH_BANK_2
#define APP_TARGET_FIRST_PAGE  (0U)
```

启动提示同步改为：

```text
APP SLOT: A @ 0x08008000
```

APP B 的槽位配置正确，本次不需要修改。

## 5. 编译

### Bootloader

```powershell
cd "D:\new project\foc2_bootloader"
cmake --build --preset Debug --clean-first
```

### APP A

```powershell
cd "D:\new project\foc2_app_a"
cmake --build --preset Debug --clean-first

D:\software\arm\bin\arm-none-eabi-objcopy.exe -O binary `
  build\Debug\foc2.elf build\Debug\foc2.bin
```

修正版 APP A：

```text
文件：D:\new project\foc2_app_a\build\Debug\foc2.bin
地址：0x08008000
大小：132376 bytes
CRC32：0x848180FA
SHA-256：D4D592F7E0B14C4BB4440AFF83285F21405D2784D8211BBA769D6BC92D7CD331
```

## 6. UART 更新步骤

先关闭占用 COM5 的串口助手，然后执行：

```powershell
python "D:\new project\iap_update_v2_begin_recovery.py" `
  COM5 `
  "D:\new project\foc2_app_a\build\Debug\foc2.bin" `
  --baud 115200 --verbose
```

成功结束应显示：

```text
OK FW END TARGET=A SIZE=132376 CRC32=0x848180FA
COMMIT=BOOTLOADER ATTEMPTS=2 RESETTING
```

更新期间不要按复位键、断电或使用 Under Reset 模式连接调试器。

## 7. 最终验收结果

修正版 A 启动后，BootHealth 连续健康检查通过并自动确认。最终状态：

```text
CURRENT=A
TARGET=B
CONFIRMED=A
PENDING=-
ATTEMPTS=0
GEN=80
```

这说明 Bootloader 已成功试运行 A，A 已通过健康门限，确认请求已提交，pending 和尝试次数已清零。

## 8. 后续维护注意事项

1. APP A 和 APP B 必须分别设置正确的槽位身份、链接地址和反向升级目标。
2. 每次构建后检查 `.isr_vector`：A 为 `0x08008000`，B 为 `0x08040000`。
3. 检查固件内的启动字符串，防止复制工程后忘记修改槽位身份。
4. trial 调试期间只使用 `mode=HOTPLUG` 读取状态。
5. `pending != NONE && attempts=0` 只能作为输入状态；Bootloader 必须先持久化清理，再启动 confirmed APP。
6. 不要直接用 SWD 改写 APP 而不更新 Metadata 中对应的 size/CRC，否则 Bootloader 会判定镜像无效。

## 9. UART 连续命令与 START 补充修复

> 下节属于历史运动测试，不是 2026-10-05 验收。本次最新结果见 [A/B 实机验收](嵌入式实习面试笔记/13_AB升级实机验收_20261005.md)：双向升级自动确认、健康失败回退及试运行升级锁通过，最终正常 B、GEN=286、驱动关闭锁存。此次没有发送 START 或其他运动指令，也没有改写 Bootloader/KVS/参数页。

### 9.1 现象

APP A 确认后，复位后的第一条 `FW STATUS` 可以响应，但后续 `START`、`RESULT` 不再响应。DMA 缓冲区中可以看到后续命令，协议变量却没有变化。

### 9.2 根因与修改

APP A 增加 BootHealth 诊断字段后，`FW STATUS` 的 `snprintf` 参数和局部缓冲区增大。ProtocolTask 原配置只有 512 words，且工程关闭了 FreeRTOS 栈溢出检测；执行长状态格式后会破坏相邻 RouterTask，表现为 Router 的 DMA 消费位置停在第一条命令末尾。

APP A、APP B 均修改为：

```c
xTaskCreate(ProtocolTask,
            "Protocol",
            1024U,
            NULL,
            2U,
            NULL);
```

### 9.3 实测结果

连续执行 `FW STATUS -> PING -> START -> STOP -> RESULT` 均正常响应。START 后系统进入：

```text
MODE=SPD
TST=RUNDOWN
TARGET=70 rpm
```

编码器累计位置由约 `0°` 增加到 `1870°`，Iq 约在 `-43 mA ~ 363 mA` 范围内，无 FOC fault，说明电机、编码器、PWM 和电流环已经实际运行。

最终结果为：

```text
OUTCOME=RUNDOWN_TIMEOUT
```

这不是启动失败，而是空载测试未达到 CONTACT 判定条件，RUNDOWN 按超时/行程保护退出并回到 IDLE。
