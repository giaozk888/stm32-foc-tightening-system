# Stage 10.9｜A 槽正常试运行：FreeRTOS 堆不足及修复

> 2026-09-26：旧 A 镜像因 FreeRTOS 堆不足试运行失败；将堆从 32 KiB 增至 40 KiB 后，修复版 A 已经由 COM5 IAP 重新升级、正常启动、通过 5 秒健康检查并自动确认。当前元数据 `CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=241`；B 保留为另一槽。

## 现场经过

用户同意正常试运行，并确认 PD6010B 输入 12 V、限流 0.5 A、B1 松开、电机固定且无工件、人员远离转轴。复位后 A 正常路径完成编码器 20/20 检查、20 kHz PWM/ADC 启动、PWM 开启状态下的电流零点校准，随后打印：

```text
APP SLOT: A @ 0x08008000
CTRL_SD=HIGH
TWO ADC RUN ZERO CAL DONE
GENERIC MOTOR-CONTROL API ENABLED
BootHealthTask CREATE FAILED
```

`BootHealthTask` 创建失败立即走错误停机，没有进入 5 秒健康检查，也**没有自动确认旧 A**。只读 SWD 检查：GPIOC ODR=`0x00000000`，TIM1 MOE 位为 0；`heap_4.c` 的 `xFreeBytesRemaining` 与 `xMinimumEverFreeBytesRemaining` 均为 `0xF0`，即 **240 B**，不足以为 512-word 栈的 BootHealthTask 分配内存。较新元数据 generation 237 保持 confirmed=B、pending=A、attempts_left=0；复位后 bootloader 清除 pending 并回退 B。

## 修复

只改 `foc2_app_a/Core/Inc/FreeRTOSConfig.h`：将 `configTOTAL_HEAP_SIZE` 从 32 KiB 提高到 **40 KiB**。不改 FOC/PWM、任务栈大小、启动逻辑或 B 槽。构建后 A 镜像仍为 **213088 B**，RAM 静态占用从 65344 B 增至 **73536 B**，在 131008 B 可用 SRAM 中占 56.13%；剩余静态余量约 57472 B，顶端 64 B mailbox 仍由链接脚本保留。

新 A 镜像 CRC32=`CB7C85FB`、SHA256=`108967863414ED1C8913D40B5BB14EB4B8E442741651693592055115D59B1611`，与旧 A 的 `50101757` 不同。A 构建、AS5047P 主机测试 4/4、TIM1/ADC 离线时序筛查通过。

## COM5 重新升级与上板验证

1. 第一次回退 B 时，COM5 无响应且 B 进入错误处理；随后确认驱动电源刚恢复 12 V。再次复位，B 的电流零点校准、编码器 20/20、UART DMA 和各任务均正常。此现象说明 B 启动依赖 PD6010B 供电，不应将无电源时的失败误判为固件损坏。
2. `FW STATUS` 显示 `CURRENT=B TARGET=A CONFIRMED=B PENDING=- GEN=238`。执行：

   ```powershell
   python -u 'D:\new project\foc2_app_a\iap_update.py' COM5 'D:\new project\foc2_app_a\build\Debug\foc2.bin'
   ```

3. 213088/213088 B 写入完成；`FW END` 返回 `CRC32=0xCB7C85FB COMMIT=BOOTLOADER ATTEMPTS=2 RESETTING`。
4. 修复版 A 正常启动，`BOOT HEALTH: PASS 5s`，请求 bootloader 自动确认并重启。重启后 `APP SLOT: A`、编码器检查 20/20、PWM 开启状态下的电流零点校准、UART DMA、各任务创建均通过；`MODE=IDLE`、`FOC/s≈20004`、`FLT=0`。
5. 再查 `FW STATUS`：`CURRENT=A TARGET=B CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=241`。`ROUTER STATUS` 显示 `DRX=17 DTX=33 PARSE=0`，ESP discovery 仍在工作。

这里只验证了启动、自动确认、空闲态控制循环和 Router；**没有执行电机转动或完整拧紧流程**。B 未被本次升级覆盖。

## 后续空闲验收

在已确认 A 上连续观察约 35 秒，12 条周期状态均为 `MODE=IDLE`、`FLT=0`、`FOC/s≈20004`，未见错误输出。随后由调试器复位，`FW STATUS` 仍为 `CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=241`；复位后的周期状态显示 `t=24000ms`、`MODE=IDLE`、`FLT=0`、`FOC/s=20004`。因此确认状态跨复位保持且 A 可再次进入正常空闲运行。此步骤仍不覆盖负载运行或长期耐久测试。
