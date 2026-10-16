---
title: Stage 8.2 - AS5047P 假 SPI 设备与完整事务测试
tags:
  - STM32G474
  - AS5047P
  - SPI
  - 单元测试
date: 2026-09-25
status: host-tests-pass-firmware-build-pass-not-flashed
---

# Stage 8.2：AS5047P 假 SPI 设备与完整事务测试

## 本步做了什么

Stage 8.1 验证了奇偶校验、回绕和转速等纯计算，但尚未验证 SPI 两帧读寄存器的**发帧顺序**。本步在 A/B 的 `Core/Inc/as5047p_transaction.h` 增加可注入 16-bit 传输回调的事务层，固件与电脑端测试共用同一段事务代码。真实固件回调仍调用原来的 `AS5047P_Transfer16()`，由 HAL 负责 SPI 和 CS；电脑端回调是脚本化假设备，逐帧核对发出的命令并返回指定响应或错误。

事务层流程：

```text
ANGLECOM 读命令 0xFFFF → READ-NOP 0xC000 → 校验响应奇偶位
                             │
                             └─ EF=1 → ERRFL 0x4001 → READ-NOP 0xC000
                                        → 再读 ANGLECOM 0xFFFF → READ-NOP 0xC000
                                        → 仍 EF=1 则失败，不输出角度
```

失败时保留传输阶段、命令、响应、HAL 返回码等 trace 信息；启动期的诊断日志改为按 trace 输出。常态仍不增加持续打印。原电机任务、SPI 配置、CS 守护延时、角度方向、故障策略均未改。A/B 新事务头文件 SHA-256 一致。

## 离线测试

`tests/as5047p_host/transaction_test.c` 的假设备逐步核对 TX 帧，并覆盖：

1. 正常角度两帧，首帧流水线旧响应不作为本次角度；
2. 第一次角度响应 EF，读取 ERRFL，再次读取角度成功（6 帧）；
3. 重试后 EF 仍在，拒绝角度；
4. 首帧、第二帧传输失败以及角度响应奇偶校验失败；
5. ERRFL 读取失败、重试角度传输失败；上述失败都不覆盖调用方旧角度值。

`ctest -V`：A/B 两套旧纯函数测试各 **147,483** 次检查通过，新事务测试各 **52** 次检查通过；共 **4/4 测试通过**。

A/B 增量固件编译与链接通过，只有原有 unused 警告：

| 槽 | Flash / 224 KiB | RAM / 131,008 B |
| --- | ---: | ---: |
| A | 225,348 B（余 4,028 B） | 65,080 B |
| B | 224,980 B（余 4,396 B） | 65,064 B |

在当前 GCC stack-usage 输出中，`AS5047P_ReadAngle` 静态栈帧报告约 280 B，事务函数约 88 B；这些数字**不能**简单相加来代替任务实际高水位。`MotorControlTask` 配置为 768 个 FreeRTOS 栈单位，工程目前 `configCHECK_FOR_STACK_OVERFLOW=0`；因此本次不因编译通过就声称运行时栈安全。

## 复现

在已配置 MSVC 开发者环境、CMake、Ninja 的工程目录：

```bat
cmake --build tests/as5047p_host/out
ctest --test-dir tests/as5047p_host/out --output-on-failure -V
```

若主机测试工程尚未配置，先执行：

```bat
cmake -S tests/as5047p_host -B tests/as5047p_host/out -G Ninja -DCMAKE_BUILD_TYPE=Release
```

固件离线构建：

```powershell
cmake --build .\foc2_app_a\build\Debug -j 4
cmake --build .\foc2_app_b\build\Debug -j 4
```

## 限制与暂停点

本次**没有烧录、复位、访问 COM5 或驱动电机**。当前板上镜像仍是第七章最后确认的版本；本地新固件尚未板上验证。假设备测试验证“软件在给定响应下发出哪些 16-bit 命令”，**不验证**真实 SPI 电平、CS 350 ns 时序、磁编码器供电/磁场、1 kHz 最坏时延、任务栈高水位，也不证明电机运动安全。后续若准备上板，应先做运行时栈与时序审计，保留已确认槽用于回退，不能因为 4/4 主机测试通过就直接开始电机实验。

相关：[[STAGE8_1_AS5047P_HOST_TESTS]]、[[SPI_PWM_现状审计_离线]]。
