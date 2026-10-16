# Stage 10.6｜A 槽完整 APP 的 ESP 通信安全启动入口

> 2026-09-26 状态：A 槽源码和离线构建完成；B1/PC13 按键极性已通过独立 SRAM 诊断实测，**完整 A 槽仍未烧录、未运行**。板上 B 槽已确认镜像与启动元数据未改动，目标现已 halt。

## 目的

此前 SRAM 诊断程序已验证 STM32 PA9/PA10 与 ESP32 GPIO18/17 的真实往返链路，以及正式 `router.c`、`esp_link.c` 的 discovery 流程。但完整 APP 的正常启动先完成 ADC/编码器/PWM/功率级初始化，随后才启动 Router/ESP；因此驱动电源断开时，不能直接用正常启动路径安全地做完整 APP 通信验收。

本步骤只修改非活动的 `foc2_app_a` 源码：启动时按住 NUCLEO-G474RE 的蓝色 **B1 USER**，经 PC13 两次采样（间隔 30 ms）选入一次性的 `SAFE COMM` 路径。默认焊桥配置下，UM2505 指明 B1 接 PC13；若实物焊桥已改接 PA0，此入口无效。2026-09-26 SRAM 实测已确认本板空闲为低、按下为高。

## 安全路径

`main()` 仍完成 CubeMX 外设配置，但**不启动** TIM1 PWM。`StartupTask` 首先令 `CTRL_SD` 输出低，并清除 TIM1 `MOE`；安全分支随后只创建 `EspLink_Task` 和 `SafeCommTask`。后者每 5 ms 维持 `CTRL_SD=0/MOE=0`、处理 Router 队列和发现/老化，每 3 秒通过 COM5 输出发现统计。

安全分支不运行 ADC 校准、编码器启动、PWM start、MotorControlTask、TighteningTask、ProtocolTask、ModbusTask，也不运行 BootHealthTask。因此 ESP32 入口继续只有 `HELLO/ANNOUNCE` 白名单，**不能经此路径下发电机、参数或 IAP 命令**；A 槽如果是待确认试运行镜像，安全启动不会把它自动确认为正式版本。松开 B1 后再次启动才走原有正常路径。

串口期望标志：

```text
SAFE COMM BOOT: B1 held; motor and IAP confirmation disabled
SAFE COMM: discovery-only Router/ESP ready; CTRL_SD remains LOW
SAFE COMM ESP_NODE=1 DISC_RX=... DISC_TX=... PARSE_ERR=0 SD_ODR=0 MOE=0
```

`SD_ODR` 和 `MOE` 是寄存器读数，**不能代替万用表对 CTRL_SD 的实测**。只有 `ESP_NODE=1` 且 `DISC_RX` 随 ESP HELLO 增加，才证明这条完整 APP 安全路径收到 ESP 消息。COM5 在安全模式下仅输出诊断，不接受通常的电机/升级命令。

## 离线验证与上板前提

```powershell
cmake --build 'D:\new project\foc2_app_a\build\Debug' -j 4
ctest --test-dir 'D:\new project\tests\as5047p_host\out' --output-on-failure
python 'D:\new project\tests\tim1_pwm_adc_timing.py'
```

本次三项离线检查均通过：A 槽 BIN **213088 B**，224 KiB 槽剩 **16288 B**，RAM **65344 B**；主机 AS5047P 回归 **4/4 通过**，TIM1/ADC 静态时序筛查通过。A 镜像 CRC32=`50101757`，SHA256=`D44E8A57DD65CFBF6E0A4DE98E30FBF55F35E58EDD5071322713CDBFCA668489`。编译器仍报告原有未使用变量/函数警告，没有新增编译错误。

完整 A 槽上板前仍需重新核实：PD6010B 输入端实测 0 V、CTRL_SD 对驱动板 GND 实测 0 V、ESP 接线牢固。B1/PC13 的实物极性已由 SRAM 诊断确认。不能直接用调试器覆盖已确认 B 槽或绕过 A/B 镜像 CRC 元数据；正式 A 槽升级需走原有 IAP，先验证安全路径，再按预定的正常启动验收流程完成 A 槽确认。**目前板上运行的不是新版 A，按 B1 不会直接进入此模式。** 若安全模式没出现或任一电压异常，应停止，不试转。

## 知识点与当前限制

- 外设**配置**与 PWM **启动**是两回事：`MX_TIM1_Init()` 只配置定时器；`HAL_TIM_PWM_Start` 等运行启动步骤均在安全分支之后的正常路径中。
- PC13 是一次性物理启动条件，ESP 串口帧不能远程解除安全模式。BootHealthTask 不在安全分支运行，避免仅凭通信测试确认电机固件。
- B1/PC13 已在独立 SRAM 程序中实测：空闲 `0`、按下 `1`、松开回 `0`，RISE/FALL 各增加 1。完整 APP 上板输出、功率级实测、IAP 试运行/回退仍**尚未验证**，不可记为测试通过。
