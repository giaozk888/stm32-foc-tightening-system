---
title: STM32 拧紧项目 C++ 参数模块化与 main 清理
date: 2026-10-02
tags: [STM32, C++, 重构, 参数存储, 单元测试]
status: 本地验证完成-未刷写
---

# 本次改动

采用 C/C++ 混合工程，而不是把 HAL、ISR 和全部业务文件统一改名为 `.cpp`。
`main.c` 仍由 C11 编译；参数模块由 C++17 编译，通过 `extern "C"` 接口连接。
A/B 两槽共用同一份参数源码，避免以后只改一槽的范围或默认值。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `tighten_params.h` | 18 个参数的 C 兼容结构、范围、默认值与接口 |
| `tighten_params.cpp` | `RecipeView`、参数查询/修改/校验/恢复默认、参数列表格式化 |
| `tighten_params_storage.h` | 参数运行状态、同步存储回调接口、加载状态 |
| `tighten_params_storage.cpp` | V1 记录布局、CRC、KVS 保存回读、旧 Flash 迁移策略 |
| A/B 的 `Core/Src/main.c` | 硬件初始化、RTOS 启动、原有任务/安全门控、KVS/Flash 硬件适配 |
| `tests/tighten_params_host/` | C/C++ ABI、参数边界、存储失败和输出兼容测试 |

`main()` 入口清理后，A 槽从 758 行缩为 86 行，B 槽从 755 行缩为 83 行。
删除的是调度器启动后、`Error_Handler()` 之后原已不可达的历史演示代码，
以及只被该演示使用的两个辅助函数和一个状态变量。旧源码可从
`refactor_backups/20261002_cpp_params/main_a.c`、`main_b.c` 恢复。

这不意味着整个 `main.c` 已完成模块化：实时 FOC、拧紧任务、协议解析、
启动流程等仍保留在原文件。本轮刻意不把控制时序改动混入参数重构。

## 不变的兼容性与安全边界

- 参数仍是原顺序的 18 个 `uint32_t`，共 72 字节；默认值、单位和范围不变。
- 持久化记录仍为 96 字节，参数偏移 16、CRC 偏移 88，版本仍为 1。
- 默认 V1 记录 CRC 为 `0x224142E1`；保留原保留字和 CRC 覆盖范围。
- 成功保存必须回读并检查完整记录；失败不能清除 DIRTY。
- KVS 缺少记录时允许旧 Flash 迁移；有记录但内容错误时不复活旧参数。
- 保留原行为：KVS I/O 错误时读旧 Flash，但不自动迁移；迁移保存失败时
  保留旧参数加载结果，`kvs_migrated` 不置位。这是兼容策略，不是新可靠性保证。
- SET 忙状态优先拒绝；拒绝修改不更改参数。运行、待启动、IAP/试运行等
  应用层门控仍由原协议/任务执行，纯参数 API 本身不是安全联锁。
- `volatile` 状态字段不等于线程安全；本轮未引入锁或改变原同步模型。
- 参数列表的字段顺序、大小写、CRLF 和元信息不变。
- 调度器异常返回仍先关闭功率级、停止 PWM、进入错误处理；删除了后续
  历史使能路径，增加无动作空循环作为错误处理函数意外返回时的兜底。
- 新增模块未使用动态分配、异常、RTTI、虚函数或全局对象动态初始化。
  ARM 目标文件未解析符号只有所需 C 库函数和参数校验接口。
  这只描述新增模块，不代表已有 Pigweed/RTOS 整个固件没有动态对象或堆。

## 已完成的本地验证

1. `tighten_params_compatibility`：独立原始默认值/范围表、18 项上下边界、
   空指针/未知名称、BUSY 优先、拒绝 SET 不变、10000 组差分校验、C ABI 调用。
2. `tighten_storage_compatibility`：独立 96 字节记录、CRC、KVS 写失败、
   回读失败/损坏、旧 Flash 加载和迁移、无效记录/有效 CRC 但参数越界、
   空记录、迁移失败、20 行参数输出逐行比较。
3. A/B 常规网络观测固件：`build/CppParams`，Release 编译链接通过。
4. A/B 安全锁定固件：`build/CppParamsSafety`，Release 编译链接通过；
   参数存储及 `PW_Kvs_*` 未被带入安全锁定 ELF。
5. 与重构前备份逐函数比较：A 槽 128 个、B 槽 126 个保留函数一致，
   仅归一化显式参数状态名称及启动默认值适配。
   检查包含 FOC 电流环、编码器更新、ADC 回调、控制/拧紧/协议/启动任务。

原有的 5 类未使用声明警告仍存在，未声称固件完全无警告；新增模块主机
测试采用 `-Wall -Wextra -Werror -pedantic`。未修改现有 NetworkObserver 构建目录。

GNU size 对比（text/data/bss，字节）：

| 槽 | 既有 NetworkObserver ELF | 新 CppParams ELF |
| --- | --- | --- |
| A | 155488 / 372 / 75328 | 154792 / 384 / 75320 |
| B | 154592 / 372 / 75304 | 153880 / 384 / 75296 |

这是与既有同配置 ELF 的大小对照；text+data 分别减少 684/700 字节，
data+bss 增加 4 字节。代码更清晰不等于已经测得实机实时性能提升。

## 如何复验

在 Windows PowerShell 的项目根目录执行：

```powershell
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;D:\software\ninja;' + $env:PATH
& 'C:\Program Files\CMake\bin\cmake.exe' -S tests/tighten_params_host -B tests/tighten_params_host/build -G Ninja '-DCMAKE_C_COMPILER=D:/Qt/Tools/mingw1310_64/bin/gcc.exe' '-DCMAKE_CXX_COMPILER=D:/Qt/Tools/mingw1310_64/bin/g++.exe' '-DCMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
& 'C:\Program Files\CMake\bin\cmake.exe' --build tests/tighten_params_host/build
& 'C:\Program Files\CMake\bin\ctest.exe' --test-dir tests/tighten_params_host/build --output-on-failure
& tests/tighten_params_host/check_preservation.ps1
```

本次没有刷写、复位、发送运动命令或修改参数 Flash。
主机测试模拟存储失败，不替代实物掉电、磨损、RTOS 并发或电机验收。
上板前仍需按当前现场状态重新确认隔离、允许刷写/复位，并做只读验收。

## 后续模块化顺序

建议下一轮先拆只读诊断/监控，再拆协议命令分发和启动服务。
拧紧状态机最后通过明确的输入快照/输出意图接口隔离；FOC ISR 保持独立 C
模块，迁移前先建立周期耗时、栈余量和行为回归测试。不要用 `.inc` 搬家
或把所有全局变量改为 `extern` 来伪装成已完成解耦。
