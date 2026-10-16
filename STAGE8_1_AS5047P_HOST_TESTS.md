---
title: Stage 8.1 - AS5047P SPI 协议与角度算法主机单元测试
tags:
  - STM32G474
  - AS5047P
  - SPI
  - 单元测试
date: 2026-09-25
status: host-tests-pass-firmware-build-pass-not-flashed
---

# Stage 8.1：AS5047P 主机单元测试

## 为什么做

第七章 PC4/PC5 模拟尖峰暂时搁置。截图所说的编码器“CRC”与当前项目不符：AS5047P 驱动实际使用**偶校验位和 EF/ERRFL**，SPI 外设硬件 CRC 关闭。本阶段先把协议与角度的纯计算从 HAL SPI 代码里分离，让电脑能直接运行与固件相同的函数；不增加上电自测，也不操作硬件。

## 修改

- A/B 各新增相同的 `Core/Inc/as5047p_protocol.h`（SHA-256 相同）。其中包括读命令偶校验、响应奇偶校验、EF 后读 ERRFL／一次重试的决策、ERRFL 位提取、14-bit 最短差值、瞬时 rpm 和电角度归一化。
- A/B 的 `main.c` 改为调用这些纯函数，SPI 收发、CS 时序、异常关断及整体任务架构不变。`AngleFrameAction()` 的前提是外层 `AS5047P_ReadRegisterFrame()` 已验证响应奇偶校验；`InstantRpm()` 的前提是调用方已保证 `dt>0`。
- 新增独立主机测试工程 `tests/as5047p_host/`。同一测试源码分别包含 A/B 的头文件，各构建一个可执行文件，不进入 STM32 镜像。

## 用例与结果

主机编译器为 MSVC 19.44，CMake + Ninja。`ctest -V`：

| 测试对象 | 结果 | 检查数 |
| --- | --- | ---: |
| A 槽纯函数 | PASS | 147,483 |
| B 槽纯函数 | PASS | 147,483 |

检查包括：已知 READ-NOP `0xC000`、ANGLECOM `0xFFFF`，全部 16,384 个 14-bit 寄存器地址生成的读命令均为偶校验；全部 32,768 个响应低 15 位组合补齐偶校验后为合法帧，单比特翻转可被识别；EF 在首次回复时要求读 ERRFL、重试后仍为 EF 时判失败；ERRFL 位提取；跨 0/16383 的 ±1 count 与 ±8192 边界；项目 `ENCODER_DIRECTION=-1` 下的 rpm 符号与电角度取模。

A/B 固件均重新编译、链接通过，有原有 unused-variable/unused-function 告警，无新增错误：

| 槽 | FLASH / 224 KiB | RAM / 131,008 B |
| --- | ---: | ---: |
| A | 225,372 B（余 4,004 B） | 65,080 B |
| B | 225,004 B（余 4,372 B） | 65,064 B |

## 复现命令

需已安装 VS 2022 Build Tools、CMake 和 Ninja。在开发者命令提示符中，从工程目录运行：

```bat
cmake -S tests/as5047p_host -B tests/as5047p_host/out -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build tests/as5047p_host/out
ctest --test-dir tests/as5047p_host/out --output-on-failure -V
```

固件离线编译：

```powershell
cmake --build .\foc2_app_a\build\Debug -j 4
cmake --build .\foc2_app_b\build\Debug -j 4
```

## 边界与下一步

本次没有烧录、复位、打开 COM5、使能驱动或启动电机。当前板上 A/B 仍是第七章最后确认的固件；源代码与板上镜像暂不一致。主机测试只验证纯函数，**不**验证 HAL SPI 传输、CS 350 ns 时序、真实磁铁偏心、信号质量、角度误码率、1 kHz 任务实时性或 20 kHz 预测误差。EF 的决策已覆盖，但真实 ERRFL 读取与重试的 I/O 序列仍需带可替换传输层的测试或安全板上验证。

若继续离线开发，优先为 SPI 传输层构造可注入的假设备并测完整两帧/EF 重试序列，同时控制 Flash 增量；暂不把本阶段源码直接烧录到当前 A 槽。参见 [[SPI_PWM_现状审计_离线]] 与 [[第七章_设备自检与保护_Obsidian总结]]。
